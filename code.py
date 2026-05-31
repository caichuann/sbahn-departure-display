"""
MatrixPortal S3 Display — Refactored Entry Point.
State-machine-driven cooperative multitasking architecture.

All blocking calls are isolated to startup (WiFi connect, NTP sync).
The main loop is a dispatcher that calls each module's tick() method.
No time.sleep() in the main loop beyond the frame-rate governor.
"""
import gc
import time
import board
from settings import (
    FRAME_TIME, MODE_MAIN, MODE_GAME, STATION_NAME,
)
from button import Button
from dino_game import DinoGame
from wifi_manager import WifiManager
from ntp_sync import NTPSync
from weather import Weather
from sbahn import SBahn
from display_manager import DisplayManager
from web_server import WebServer
from mode_manager import ModeManager
from location_resolver import resolve_station


# ═══════════════════════════════════════════════════════════════════
# Startup — blocking initialization (acceptable: only runs once)
# ═══════════════════════════════════════════════════════════════════
print("=" * 40)
print("MatrixPortal S3 starting...")
print("=" * 40)

# Create core modules (no network needed)
mode_mgr = ModeManager()
display_mgr = DisplayManager()
btn_up = Button(board.BUTTON_UP)
btn_down = Button(board.BUTTON_DOWN)
dino_game = DinoGame()

# Initialize display
display_mgr.init_display(dino_game=dino_game)

# WiFi — blocking initial connect (with max retries, gives up and enters offline mode)
wifi_mgr = WifiManager()

class _OfflineStub:
    """Placeholder for network modules when WiFi is unavailable at startup.
    Has the same interface as the real modules so the main loop doesn't crash."""
    temperature = None
    weather_code = None
    is_day = 1
    status = "offline"
    departures = []
    info_text = ""
    data_version = -1
    synced = False

    def tick(self): pass
    def close(self): pass
    def get_local_time(self):
        """Read RTC directly — works offline if NTP previously synced."""
        utc = time.localtime()
        tz = 2 if (3 < utc.tm_mon < 10) else 1  # rough CET/CEST, good enough
        h = (utc.tm_hour + tz) % 24
        return h, utc.tm_min

def build_network_modules():
    """Build network-dependent modules. Resolves station name against the
    MVG locations API — works both at startup and during WiFi reconnects.
    Returns None if station resolution fails."""
    sid, lat, lon = resolve_station(STATION_NAME, wifi_mgr.pool, wifi_mgr.ssl_context)
    if not sid:
        return None
    return (
        NTPSync(wifi_mgr.pool),
        Weather(wifi_mgr.pool, wifi_mgr.ssl_context, lat, lon),
        SBahn(wifi_mgr.pool, wifi_mgr.ssl_context, sid),
        WebServer(wifi_mgr.pool, mode_mgr, dino_game),
    )

wifi_ok = wifi_mgr.ensure_connected()

if wifi_ok:
    modules = build_network_modules()
else:
    modules = None

if modules is not None:
    ntp_sync, weather, sbahn, web_server = modules
    _network_connection_id = wifi_mgr.connection_id
    ntp_sync.sync_now()
    display_mgr.update_clock(*ntp_sync.get_local_time())
    display_mgr.train_dest_labels[0].text = "Loading..."
    display_mgr.train_dest_labels[0].x = 0
else:
    if wifi_ok:
        display_mgr.show_status("No Station")
    else:
        display_mgr.show_status("Offline")
    _network_connection_id = -1
    ntp_sync = _OfflineStub()
    weather = _OfflineStub()
    sbahn = _OfflineStub()
    web_server = _OfflineStub()

gc.collect()
try:
    print("Startup complete. Free memory:", gc.mem_free())
except AttributeError:
    print("Startup complete.")

# ═══════════════════════════════════════════════════════════════════
# Main loop — cooperative tick scheduling
# ═══════════════════════════════════════════════════════════════════
_last_clock_update = 0.0
_last_temp_update = -9999.0
_last_gc = 0.0
_prev_mode = MODE_MAIN
_prev_sbahn_version = -1    # Track sbahn data version for changes
_weather_data_changed = False

while True:
    t0 = time.monotonic()

    # ── 1. Network health ─────────────────────────────────────────
    wifi_mgr.tick()
    if wifi_mgr.connected and wifi_mgr.connection_id != _network_connection_id:
        try:
            web_server.close()
        except Exception:
            pass
        modules = build_network_modules()
        if modules is not None:
            ntp_sync, weather, sbahn, web_server = modules
            _network_connection_id = wifi_mgr.connection_id
            _prev_sbahn_version = -1
            _weather_data_changed = True
            display_mgr.show_status("Net OK")
            print("Network modules rebuilt")
        else:
            display_mgr.show_status("Sta Err")
            print("Station resolution failed during reconnect")

    # ── 2. Network operations (only if WiFi is up) ─────────────────
    if wifi_mgr.connected:
        try:
            ntp_sync.tick()
        except Exception as e:
            print(f"NTP tick error: {e}")

        try:
            prev_temp = weather.temperature
            prev_wcode = weather.weather_code
            weather.tick()
            if weather.temperature != prev_temp or weather.weather_code != prev_wcode:
                _weather_data_changed = True
        except Exception as e:
            print(f"Weather tick error: {e}")

        try:
            sbahn.tick()
        except Exception as e:
            print(f"SBahn tick error: {e}")
            if sbahn.status == "loading":
                display_mgr.show_status("SBahn Err")

    # ── 3. Buttons + mode switching ───────────────────────────────
    if btn_up.pressed:
        mode_mgr.cycle(-1)
        print(f"Mode: {mode_mgr.name}")
    if btn_down.pressed:
        mode_mgr.cycle(1)
        print(f"Mode: {mode_mgr.name}")

    # ── 4. Web server ─────────────────────────────────────────────
    web_server.tick()

    # ── 5. Mode-aware display updates ─────────────────────────────
    current_mode = mode_mgr.mode

    if current_mode == MODE_MAIN:
        # Clock (every 10s)
        if t0 - _last_clock_update >= 10.0:
            display_mgr.update_clock(*ntp_sync.get_local_time())
            _last_clock_update = t0

        # Weather: update when data changes OR every 30s
        if _weather_data_changed or t0 - _last_temp_update >= 30.0:
            display_mgr.update_weather(
                weather.temperature,
                weather.weather_code,
                weather.is_day,
            )
            _last_temp_update = t0
            _weather_data_changed = False
            # Show weather status on display row 1 time position
            if weather.status == "error" and weather.temperature is None:
                display_mgr.info_scroll.set(
                    display_mgr.info_label, "W:err")

        # S-Bahn: only update display when new data arrives
        if sbahn.data_version != _prev_sbahn_version:
            if sbahn.status == "ok":
                display_mgr.update_sbahn_rows(sbahn.departures)
            elif sbahn.status == "empty":
                display_mgr.update_sbahn_rows([], sbahn.info_text)
                display_mgr.scroll_rows[0].set(
                    display_mgr.train_dest_labels[0], "Cancelled")
                display_mgr.set_row_icon(0, True, "S")
            elif sbahn.status == "error":
                display_mgr.show_status("Net Err")
            _prev_sbahn_version = sbahn.data_version

    # ── 6. Handle mode transition ─────────────────────────────────
    if current_mode != _prev_mode:
        if current_mode == MODE_GAME:
            dino_game.reset()
        display_mgr.set_mode(current_mode)
        _prev_mode = current_mode

    # ── 7. Per-frame ticks ────────────────────────────────────────
    display_mgr.tick()  # scroll animations (works in both modes)

    if current_mode == MODE_GAME:
        dino_game.tick()

    # ── 8. Periodic GC safety net ─────────────────────────────────
    if t0 - _last_gc >= 30.0:
        gc.collect()
        _last_gc = t0

    # ── 9. Frame rate governor ────────────────────────────────────
    elapsed = time.monotonic() - t0
    remaining = FRAME_TIME - elapsed
    if remaining > 0:
        time.sleep(remaining)
