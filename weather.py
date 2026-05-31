"""
Open-Meteo weather data fetcher using non-blocking HTTPClient.
State-machine-driven — no blocking calls in tick().
"""
import time
import gc
from http_client import HTTPClient
from settings import WEATHER_REFRESH_SEC, WEATHER_RETRY_SEC


# ── States ─────────────────────────────────────────────────────────
(
    S_IDLE,        # Waiting for refresh interval
    S_FETCHING,    # HTTP request in progress (non-blocking)
    S_READY,       # Data parsed successfully
    S_ERROR,       # HTTP or parse error
) = range(4)


class Weather:
    def __init__(self, pool, ssl_context, lat, lon):
        self._http = HTTPClient(pool, ssl_context)
        self._lat = lat
        self._lon = lon
        self.temperature = None     # float or None
        self.weather_code = None    # int or None
        self.is_day = 1             # int 0/1
        self.status = "ok"

        self._state = S_IDLE
        self._last_fetch = -9999.0
        self._retry_interval = WEATHER_REFRESH_SEC

    def tick(self):
        """Non-blocking tick. Call every main loop iteration."""
        now = time.monotonic()

        if self._state == S_IDLE:
            if now - self._last_fetch >= self._retry_interval:
                self._start_fetch()
                self._state = S_FETCHING

        elif self._state == S_FETCHING:
            self._http.tick()
            if self._http.done:
                if self._http.status_code == 200:
                    self._parse_response()
                    self._state = S_READY
                else:
                    print(f"Weather HTTP {self._http.status_code}: {self._http.error_msg}")
                    self._state = S_ERROR
                self._http.reset()

        elif self._state == S_READY:
            self._last_fetch = time.monotonic()
            self._retry_interval = WEATHER_REFRESH_SEC
            self._state = S_IDLE

        elif self._state == S_ERROR:
            self.temperature = None
            self.weather_code = None
            self.is_day = 1
            self.status = "error"
            self._last_fetch = now - WEATHER_REFRESH_SEC + WEATHER_RETRY_SEC
            self._retry_interval = WEATHER_RETRY_SEC
            self._state = S_IDLE

    def _start_fetch(self):
        url = (f"https://api.open-meteo.com/v1/forecast"
               f"?latitude={self._lat}&longitude={self._lon}"
               f"&current_weather=true&temperature_unit=celsius")
        self._http.get(url, timeout=15)

    def _parse_response(self):
        """Parse Open-Meteo JSON response."""
        try:
            data = self._http.json()
        except Exception as e:
            print(f"Weather JSON parse error: {e}")
            self._state = S_ERROR
            return

        if isinstance(data, dict):
            cw = data.get("current_weather", {})
            self.temperature = (float(cw["temperature"])
                                if cw.get("temperature") is not None
                                else None)
            self.weather_code = (int(cw["weathercode"])
                                 if cw.get("weathercode") is not None
                                 else None)
            self.is_day = int(cw.get("is_day", 1))
            self.status = "ok"
            print(f"Weather OK: {self.temperature}C code={self.weather_code}")
        else:
            self._state = S_ERROR
            return

        gc.collect()
