"""
Configuration constants for the MatrixPortal S3 display.
Reads from either os.getenv() (CircuitPython settings.toml) or settings.toml file.
"""
import os

# ── Settings helpers ───────────────────────────────────────────────
def _setting(name):
    """Read a setting from environment or settings.toml file."""
    value = os.getenv(name)
    if value is not None:
        return value
    # Fallback: read from settings.toml (for simulator / desktop CPython)
    try:
        path = getattr(os, "path", None)
        search_dirs = (
            os.getcwd(),
            path.dirname(__file__),
            path.dirname(path.dirname(__file__)),
        )
    except Exception:
        search_dirs = ()
    for search_dir in search_dirs:
        try:
            toml_path = path.join(search_dir, "settings.toml")
            if os.path.exists(toml_path):
                with open(toml_path) as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(name + " ="):
                            val = line.split("=", 1)[1].strip().strip('"')
                            return val
        except Exception:
            pass
    return ""

STATION_NAME = _setting("SBAHN_STATION_NAME")

if not STATION_NAME:
    print("[settings] Warning: SBAHN_STATION_NAME not set — station lookup will fail")

# ── Timing ─────────────────────────────────────────────────────────
REFRESH_INTERVAL     = 30
SCROLL_PAUSE_SEC     = 5.0
FRAME_TIME           = 1 / 30
WEATHER_REFRESH_SEC  = 300
WEATHER_RETRY_SEC    = 30
REFRESH_RETRY_SEC    = 10
WIFI_RETRY_SEC       = 10
NTP_RETRY_SEC        = 60

HTTP_TIMEOUT         = 15
NTP_CACHE_SECONDS    = 3600

# ── Layout (64×64 matrix, rotation 90) ────────────────────────────
CHAR_W  = 6
ROW_Y   = (5, 15, 26, 36)
ICON_W  = 14
WEATHER_ICON_X = 6
WEATHER_ICON_Y = 43

# ── Mode names ─────────────────────────────────────────────────────
MODE_NAMES = ["S-Bahn Info", "T-Rex"]
MODE_MAIN  = 0
MODE_GAME  = 1

# ── Colors ─────────────────────────────────────────────────────────
COLOR_WHITE  = 0xFFFFFF
COLOR_RED    = 0xFC4349
COLOR_BLUE   = 0x6DBCDB
COLOR_YELLOW = 0xF3B562
COLOR_BLACK  = 0x000000

# ── Asset paths ────────────────────────────────────────────────────
FONT_PATH        = "fonts/6x10.bdf"
WEATHER_ICON_DIR = "images/weather/"

# ── Font (loaded once, imported by other modules) ──────────────────
from adafruit_bitmap_font import bitmap_font
FONT = bitmap_font.load_font(FONT_PATH)
