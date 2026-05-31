"""
MVG S-Bahn departure fetcher state machine.
Uses HTTPClient for non-blocking HTTPS requests.
Parses MVG API response and provides formatted display data.
"""
import time
import gc
from http_client import HTTPClient
from settings import REFRESH_INTERVAL, REFRESH_RETRY_SEC


# ── States ─────────────────────────────────────────────────────────
(
    S_IDLE_F,       # Waiting for refresh interval
    S_FETCHING,     # HTTP request in progress
    S_READY,        # Data available (success, empty, or cancelled)
    S_ERROR,        # Network or parse error
) = range(4)


class SBahn:
    def __init__(self, pool, ssl_context, station_id):
        self._http = HTTPClient(pool, ssl_context)
        self._station_id = station_id

        # Public data — readable by display_manager at any time
        self.departures = []       # List of display-ready dicts (up to 2)
        self.info_text = ""        # Info message when all cancelled
        self.status = "loading"    # "loading", "ok", "empty", "error"
        self.data_version = 0      # Incremented each time new data arrives

        self._state = S_IDLE_F
        self._last_fetch = -9999.0
        self._retry_interval = REFRESH_INTERVAL

    def tick(self):
        """Non-blocking tick. Call every main loop iteration."""
        now = time.monotonic()

        if self._state == S_IDLE_F:
            if now - self._last_fetch >= self._retry_interval:
                self._start_fetch()
                self._state = S_FETCHING

        elif self._state == S_FETCHING:
            self._http.tick()
            if self._http.done:
                if self._http.status_code == 200:
                    self._parse_response()
                else:
                    print(f"SBahn HTTP {self._http.status_code}: {self._http.error_msg}")
                    self._state = S_ERROR
                self._http.reset()

        elif self._state in (S_READY, S_ERROR):
            if self._state == S_ERROR:
                self.departures = []
                self.info_text = ""
                self.status = "error"
                self.data_version += 1
                self._last_fetch = now - REFRESH_INTERVAL + REFRESH_RETRY_SEC
                self._retry_interval = REFRESH_RETRY_SEC
            self._state = S_IDLE_F

    def _start_fetch(self):
        url = (f"https://www.mvg.de/api/bgw-pt/v3/departures"
               f"?globalId={self._station_id}&limit=20")
        self._http.get(url, timeout=20)

    def _parse_response(self):
        """Parse MVG JSON response into display-ready departure data."""
        try:
            data = self._http.json()
        except Exception as e:
            print(f"SBahn JSON parse error: {e}")
            self._state = S_ERROR
            return

        if not isinstance(data, list):
            self._state = S_ERROR
            return

        # Filter to S-Bahn departures
        sbahn_all = [
            d for d in data
            if (d.get("transportType") == "SBAHN"
                or d.get("label", "").startswith("S"))
        ]

        # Separate normal vs cancelled
        normal_deps = [d for d in sbahn_all if not d.get("cancelled")]

        if normal_deps:
            # Format up to 2 departures for display
            formatted = []
            for dep in normal_deps[:2]:
                dest_full = dep.get("destination", "Unknown")
                # Check for "Fährt nur bis xxx" messages
                for msg in dep.get("messages", []):
                    m_text = (
                        msg if isinstance(msg, str)
                        else (msg.get("text") or msg.get("title") or "")
                    )
                    if m_text.startswith("Fährt nur bis "):
                        dest_full = m_text[len("Fährt nur bis "):].strip()
                        break

                realtime = dep.get("realtimeDepartureTime")
                planned = dep.get("plannedDepartureTime")
                dep_ms = realtime or planned or 0

                if dep_ms <= 0:
                    time_str = "--min"
                    delay_min = 0
                else:
                    now = int(time.time())
                    minutes = max(dep_ms // 1000 - now, 0) // 60
                    time_str = f"{minutes}min"
                    delay_min = 0
                    if realtime and planned and realtime != planned:
                        delay_min = (realtime - planned) // 60000
                    if delay_min > 0:
                        time_str = f"{time_str}(+{delay_min})"

                formatted.append({
                    "destination": dest_full,
                    "time_str": time_str,
                    "delay_min": delay_min,
                    "has_data": True,
                    "line_label": dep.get("label", "S"),
                })

            self.departures = formatted
            self.info_text = ""
            self.status = "ok"
            self.data_version += 1
            self._last_fetch = time.monotonic()
            self._retry_interval = REFRESH_INTERVAL
            print(f"SBahn: {len(formatted)} departures")
        else:
            # All cancelled — find info text from any S-Bahn departure
            self.departures = []
            info_text = ""
            for dep in sbahn_all:
                for info in dep.get("infos", []):
                    if info.get("type", "") == "EARLY_TERMINATION":
                        continue
                    msg = info.get("message", "").strip()
                    itype = info.get("type", "").strip()
                    if msg:
                        info_text = f"[{itype}]{msg}" if itype else msg
                        break
                if info_text:
                    break
            self.info_text = info_text
            self.status = "empty"
            self.data_version += 1
            self._last_fetch = time.monotonic()
            self._retry_interval = REFRESH_INTERVAL
            print(f"SBahn: all cancelled, info='{info_text[:40]}...'")

        gc.collect()
        self._state = S_READY
