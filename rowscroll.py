"""
Horizontal text-scrolling state machine.
States: PAUSING → SCROLLING → PAUSING (loop).
Already non-blocking — extracted verbatim from original code.
"""
import time
from settings import CHAR_W, ICON_W, SCROLL_PAUSE_SEC, COLOR_WHITE

PAUSING, SCROLLING = 0, 1


class RowScroll:
    def __init__(self, x_start=None):
        self.active = False
        self.text_width_px = 0
        self.x_offset = 0
        self.state = PAUSING
        self.next_time = 0.0
        self.x_start = x_start  # None = use ICON_W

    def _xs(self):
        return self.x_start if self.x_start is not None else ICON_W

    def set(self, dest_label, full_text):
        xs = self._xs()
        dest_label.text = full_text
        dest_label.x = xs
        dest_label.color = COLOR_WHITE
        self.text_width_px = len(full_text) * CHAR_W
        self.x_offset = 0
        self.active = (xs + self.text_width_px) > 64
        if self.active:
            self.state = PAUSING
            self.next_time = time.monotonic() + SCROLL_PAUSE_SEC

    def clear(self, dest_label):
        dest_label.text = ""
        dest_label.x = self._xs()
        self.active = False
        self.x_offset = 0

    def tick(self, dest_label):
        if not self.active:
            return
        xs = self._xs()
        now = time.monotonic()
        if self.state == PAUSING:
            if now >= self.next_time:
                self.state = SCROLLING
            return
        # SCROLLING
        self.x_offset -= 1
        dest_label.x = xs + self.x_offset
        if self.x_offset <= -self.text_width_px:
            self.x_offset = 0
            dest_label.x = xs
            self.state = PAUSING
            self.next_time = now + SCROLL_PAUSE_SEC
