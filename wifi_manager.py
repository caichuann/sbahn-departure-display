"""
WiFi connection manager with reconnect state machine.
Monitors wifi.radio.connected and handles reconnection.
The only unavoidable blocking call is wifi.radio.connect() (~1-3s).
"""
import os
import time
import wifi
import socketpool
import ssl
from settings import WIFI_RETRY_SEC


# ── States ─────────────────────────────────────────────────────────
(
    S_CONNECTED,      # WiFi up, everything normal
    S_CHECKING,       # periodic health probe
    S_DISCONNECTED,   # WiFi down detected
    S_CONNECTING,     # attempting wifi.radio.connect()
    S_WAIT_RETRY,     # waiting before next reconnect attempt
) = range(5)


MAX_STARTUP_ATTEMPTS = 10  # ~100s total (10 × 10s retry interval)


class WifiManager:
    CHECK_INTERVAL = 5.0  # seconds between health probes

    def __init__(self):
        self.connected = False
        self.pool = None
        self.ssl_context = None
        self._connection_id = 0
        self._state = S_DISCONNECTED
        self._last_check = 0.0
        self._last_attempt = 0.0
        self._ssid = os.getenv("CIRCUITPY_WIFI_SSID")
        self._password = os.getenv("CIRCUITPY_WIFI_PASSWORD")

    @property
    def connection_id(self):
        """Monotonically increases each time a new SocketPool is created."""
        return self._connection_id

    def ensure_connected(self):
        """
        Blocking initial WiFi connect. Used only during startup.
        Returns True on success, False after max attempts.
        On failure the state machine stays in S_DISCONNECTED and
        tick() will continue background retries.
        """
        print("Connecting WiFi...")
        for attempt in range(1, MAX_STARTUP_ATTEMPTS + 1):
            try:
                wifi.radio.connect(self._ssid, self._password)
                self._on_connected()
                print(f"WiFi OK: {wifi.radio.ipv4_address}")
                return True
            except Exception as e:
                print(f"WiFi attempt {attempt}/{MAX_STARTUP_ATTEMPTS} failed: {e}")
                if attempt < MAX_STARTUP_ATTEMPTS:
                    time.sleep(WIFI_RETRY_SEC)
        print("WiFi: giving up after max attempts, entering offline mode")
        self._state = S_DISCONNECTED
        return False

    def tick(self):
        """
        Non-blocking state machine tick. Call every main loop iteration.
        Only does work when the state requires it.
        """
        now = time.monotonic()

        if self._state == S_CONNECTED:
            if now - self._last_check >= self.CHECK_INTERVAL:
                self._state = S_CHECKING

        elif self._state == S_CHECKING:
            if wifi.radio.connected:
                # Check that we have a valid IP
                try:
                    ip = wifi.radio.ipv4_address
                    if ip is not None:
                        self._last_check = now
                        self._state = S_CONNECTED
                        return
                except Exception:
                    pass
            # WiFi is down
            print("WiFi lost, reconnecting...")
            self.connected = False
            self._state = S_CONNECTING

        elif self._state == S_DISCONNECTED:
            self._state = S_CONNECTING

        elif self._state == S_CONNECTING:
            try:
                wifi.radio.connect(self._ssid, self._password)
                self._on_connected()
                print(f"WiFi reconnected: {wifi.radio.ipv4_address}")
            except Exception as e:
                print(f"WiFi reconnect failed: {e}")
                self._last_attempt = now
                self._state = S_WAIT_RETRY

        elif self._state == S_WAIT_RETRY:
            if now - self._last_attempt >= WIFI_RETRY_SEC:
                self._state = S_CONNECTING

    def _on_connected(self):
        """Called after a successful wifi.radio.connect()."""
        self.connected = True
        self.pool = socketpool.SocketPool(wifi.radio)
        self.ssl_context = ssl.create_default_context()
        self._connection_id += 1
        self._last_check = time.monotonic()
        self._state = S_CONNECTED
