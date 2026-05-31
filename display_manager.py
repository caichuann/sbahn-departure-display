"""
Display layout and rendering manager.
Sets up the 64×64 matrix, all labels, icons, and display groups.
Reads data from weather/sbahn modules and updates the display.
Does NOT perform any network I/O.
"""
import gc
import displayio
from adafruit_display_text.bitmap_label import Label
from adafruit_matrixportal.matrix import Matrix

from settings import (
    FONT, CHAR_W, ROW_Y, ICON_W, COLOR_WHITE, COLOR_RED, COLOR_BLUE,
    COLOR_BLACK, WEATHER_ICON_X, WEATHER_ICON_Y,
    WEATHER_ICON_DIR, MODE_MAIN, MODE_GAME,
)
from rowscroll import RowScroll


# ── Weather icon mapping ───────────────────────────────────────────
def weathercode_to_bmp(code, is_day=1):
    """Map WMO weather code to icon filename (without extension)."""
    if code in (0, 1):
        return "sunny" if is_day else "sunny_night"
    if code == 2:
        return "partly_cloudy" if is_day else "partly_cloudy_night"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53):
        return "drizzle"
    if code == 55:
        return "rain"
    if code in (56, 57):
        return "sleet"
    if 61 <= code <= 63:
        return "rain"
    if 64 <= code <= 67:
        return "heavy_rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 80 <= code <= 82:
        return "rain"
    if code in (83, 84):
        return "sleet"
    if code in (95, 96, 99):
        return "thunder"
    return "unknown"



class DisplayManager:
    def __init__(self):
        # Matrix & display
        self.matrix = Matrix(width=64, height=64, bit_depth=4)
        self.display = self.matrix.display
        self.display.rotation = 90

        # Groups
        self.main_group = displayio.Group()
        self.game_group = displayio.Group()

        # Labels — created in init_display()
        self.train_dest_labels = []
        self.train_time_labels = []
        self.info_label = None
        self.temp_label = None
        self.time_label = None
        self.weather_icon_grid = None
        self.weather_icon_index = 0

        # Line badge icons (rendered, not BMP)
        self.badge_grids = []
        self.badge_labels = []

        # Scroll state machines
        self.scroll_rows = [RowScroll(), RowScroll()]
        self.info_scroll = RowScroll(x_start=0)

        # Weather icon cache (OnDiskBitmap + open file handle, same as reference)
        self._weather_icon_cache = {}
        self._weather_file_cache = {}
        self._last_icon_name = None

        # Badge bitmap cache — keyed by line_name, avoids recreating bitmaps
        self._badge_cache = {}

        # Current mode tracking
        self._current_mode = MODE_MAIN

    # ── Initialization ─────────────────────────────────────────────
    def init_display(self, dino_game=None):
        """Create all labels, groups, and initial display state."""
        main = self.main_group

        # Destination + time labels for 2 departure rows
        for i in range(2):
            dest_lbl = Label(FONT, text="", color=COLOR_WHITE)
            dest_lbl.x = ICON_W
            dest_lbl.y = ROW_Y[i * 2]
            main.append(dest_lbl)
            self.train_dest_labels.append(dest_lbl)

            time_lbl = Label(FONT, text="", color=COLOR_WHITE)
            time_lbl.x = 0
            time_lbl.y = ROW_Y[i * 2 + 1]
            main.append(time_lbl)
            self.train_time_labels.append(time_lbl)

        # Info label (used when all departures cancelled)
        self.info_label = Label(FONT, text="", color=COLOR_WHITE)
        self.info_label.x = 0
        self.info_label.y = ROW_Y[1]
        main.append(self.info_label)

        # Line badge icons for each departure row (rendered, not BMP)
        for i in range(2):
            badge_bmp, badge_pal = self._make_line_badge(COLOR_BLUE)
            badge_grid = displayio.TileGrid(badge_bmp, pixel_shader=badge_pal)
            badge_grid.x = 0
            badge_grid.y = ROW_Y[i * 2] - 4
            badge_grid.hidden = True
            main.append(badge_grid)
            self.badge_grids.append(badge_grid)

            line_lbl = Label(FONT, text="", color=COLOR_WHITE)
            line_lbl.x = 1
            line_lbl.y = ROW_Y[i * 2]
            line_lbl.hidden = True
            main.append(line_lbl)
            self.badge_labels.append(line_lbl)
        print("Line badges created")

        # Weather icon placeholder
        blank_palette = displayio.Palette(1)
        blank_palette[0] = COLOR_BLACK
        blank_bitmap = displayio.Bitmap(11, 11, 1)
        self.weather_icon_grid = displayio.TileGrid(
            blank_bitmap, pixel_shader=blank_palette
        )
        self.weather_icon_grid.x = WEATHER_ICON_X
        self.weather_icon_grid.y = WEATHER_ICON_Y
        main.append(self.weather_icon_grid)
        self.weather_icon_index = len(main) - 1

        # Temperature label
        self.temp_label = Label(FONT, text="--°C", color=COLOR_WHITE)
        self.temp_label.x = 0
        self.temp_label.y = 59
        main.append(self.temp_label)

        # Clock label
        self.time_label = Label(FONT, text="--:--", color=COLOR_WHITE)
        self.time_label.x = 64 - len("--:--") * CHAR_W + 1
        self.time_label.y = 59
        main.append(self.time_label)

        # Game group
        if dino_game is not None:
            game_tg = dino_game.make_tilegrid()
            if game_tg:
                self.game_group.append(game_tg)

        # Set initial root group
        self.display.root_group = main
        print("Display initialized")

    # ── Line colors (RGB 0-1 converted to 0xRRGGBB) ─────────────
    LINE_COLORS = {
        'S1': 0x58B8E2,  # 0.345, 0.722, 0.886
        'S2': 0x86B647,  # 0.525, 0.714, 0.278
        'S3': 0x8A2B7E,  # 0.541, 0.169, 0.494
        'S4': 0xD0312A,  # 0.816, 0.192, 0.165
        'S5': 0x00517C,  # 0.000, 0.318, 0.486
        'S6': 0x009464,  # 0.000, 0.581, 0.392
        'S7': 0x893B2F,  # 0.537, 0.231, 0.184
        'S8': 0xF7CD48,  # 0.969, 0.804, 0.282
    }

    # ── Line badge helpers ────────────────────────────────────────
    @staticmethod
    def _make_line_badge(line_color):
        """Create a 14x10 line badge bitmap with rounded corners.
        Last column (x=13) and last row (y=9) are black.
        Four corners of the colored area (excluding the black column/row)
        are also black: (0,0) (12,0) (0,8) (12,8).
        Remaining area filled with line_color."""
        bmp = displayio.Bitmap(14, 10, 2)
        pal = displayio.Palette(2)
        pal[0] = COLOR_BLACK
        pal[1] = line_color

        for y in range(10):
            for x in range(14):
                if x == 13 or y == 9:
                    bmp[x, y] = 0
                elif (x == 0 and y == 0) or (x == 12 and y == 0) or \
                     (x == 0 and y == 8) or (x == 12 and y == 8):
                    bmp[x, y] = 0
                else:
                    bmp[x, y] = 1
        return bmp, pal

    # ── Weather icon helpers ───────────────────────────────────────
    def _load_weather_icon(self, name):
        """Load a weather icon as OnDiskBitmap (reads directly from flash).
        Same approach as the reference/working code."""
        if name in self._weather_icon_cache:
            return self._weather_icon_cache[name]
        try:
            f = open(f"{WEATHER_ICON_DIR}{name}.bmp", "rb")
            bmp = displayio.OnDiskBitmap(f)
            self._weather_file_cache[name] = f
            self._weather_icon_cache[name] = bmp
            print(f"Weather icon loaded: {name} {bmp.width}x{bmp.height}")
            return bmp
        except Exception as e:
            print(f"Weather icon load failed {name}: {e}")
            return None

    # ── Display update methods ─────────────────────────────────────
    def update_weather(self, temperature, weather_code, is_day):
        """Update temperature label and weather icon on the display."""
        # Temperature text & color
        if temperature is None:
            self.temp_label.text = "--°C"
        else:
            self.temp_label.text = f"{int(round(temperature))}°C"
        self.temp_label.color = COLOR_WHITE

        # Weather icon
        icon_name = (weathercode_to_bmp(weather_code, is_day)
                     if weather_code is not None else "unknown")
        if icon_name == self._last_icon_name:
            return  # No change needed

        icon_bmp = self._load_weather_icon(icon_name)
        if icon_bmp is not None:
            try:
                self.main_group.remove(self.weather_icon_grid)
            except Exception:
                pass
            self.weather_icon_grid = displayio.TileGrid(
                icon_bmp, pixel_shader=icon_bmp.pixel_shader,
                x=WEATHER_ICON_X, y=WEATHER_ICON_Y)
            self.main_group.insert(self.weather_icon_index,
                                   self.weather_icon_grid)
            self._last_icon_name = icon_name

    def update_clock(self, local_hour, local_min):
        """Update the on-screen clock."""
        txt = f"{local_hour:02d}:{local_min:02d}"
        self.time_label.text = txt
        self.time_label.x = 64 - len(txt) * CHAR_W + 1

    def update_sbahn_rows(self, departures, info_text=""):
        """
        Update S-Bahn departure rows from prepared departure data.
        departures: list of dicts with keys:
            destination, time_str, delay_min, has_data, line_label
        """
        for i in range(2):
            if i < len(departures) and departures[i].get("has_data"):
                dep = departures[i]
                dest = dep["destination"]
                # Only restart scrolling if destination name actually changed
                if self.train_dest_labels[i].text != dest:
                    self.scroll_rows[i].set(self.train_dest_labels[i], dest)
                # Always update time (doesn't affect scroll)
                self.train_time_labels[i].text = dep["time_str"]
                self.train_time_labels[i].color = (
                    COLOR_RED if dep.get("delay_min", 0) >= 3 else COLOR_WHITE)
                self.train_time_labels[i].x = (
                    64 - len(dep["time_str"]) * CHAR_W + 1)
                self.set_row_icon(i, True, dep.get("line_label", "S"))
            else:
                self.scroll_rows[i].clear(self.train_dest_labels[i])
                self.train_time_labels[i].text = ""
                self.set_row_icon(i, False)

        # Info text (cancelled mode)
        if info_text:
            self.info_scroll.set(self.info_label, info_text)
        else:
            self.info_scroll.clear(self.info_label)

    def show_status(self, row0_text, row0_color=COLOR_RED):
        """Show a one-line status message on the first row."""
        self.scroll_rows[0].clear(self.train_dest_labels[0])
        self.train_dest_labels[0].text = row0_text
        self.train_dest_labels[0].x = 0
        self.train_dest_labels[0].color = row0_color
        self.scroll_rows[0].active = False
        for i in range(2):
            self.set_row_icon(i, False)
            self.train_time_labels[i].text = ""

    # ── Per-frame tick ─────────────────────────────────────────────
    def tick(self):
        """Called every main loop iteration. Ticks scroll animations."""
        for i, row in enumerate(self.scroll_rows):
            row.tick(self.train_dest_labels[i])
        self.info_scroll.tick(self.info_label)

    def set_mode(self, mode):
        """Switch the active display group. Returns True if changed."""
        if mode == self._current_mode:
            return False
        self._current_mode = mode
        if mode == MODE_GAME:
            self.display.root_group = self.game_group
        else:
            self.display.root_group = self.main_group
        return True

    @staticmethod
    def _text_color_for_bg(bg_color):
        """Return black or white text color based on background luminance."""
        r = (bg_color >> 16) & 0xFF
        g = (bg_color >> 8) & 0xFF
        b = bg_color & 0xFF
        # Perceived brightness (ITU-R BT.601)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return COLOR_BLACK if luminance > 140 else COLOR_WHITE

    def set_row_icon(self, i, visible, line_name=""):
        """Show or hide the line badge icon and label for departure row i."""
        if i < len(self.badge_grids):
            self.badge_grids[i].hidden = not visible
            self.badge_labels[i].hidden = not visible
            if visible and line_name:
                self.badge_labels[i].text = line_name
                # Only rebuild badge bitmap when line_name changes
                cached = self._badge_cache.get(line_name)
                if cached is not None:
                    self.badge_grids[i].bitmap, self.badge_grids[i].pixel_shader = cached
                else:
                    line_color = self.LINE_COLORS.get(line_name, COLOR_BLACK)
                    new_bmp, new_pal = self._make_line_badge(line_color)
                    self._badge_cache[line_name] = (new_bmp, new_pal)
                    self.badge_grids[i].bitmap = new_bmp
                    self.badge_grids[i].pixel_shader = new_pal
                # Set text color for contrast against badge background
                line_color = self.LINE_COLORS.get(line_name, COLOR_BLACK)
                self.badge_labels[i].color = self._text_color_for_bg(line_color)
