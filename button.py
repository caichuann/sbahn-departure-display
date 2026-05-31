"""
Debounced GPIO button driver.
Non-blocking — the `.pressed` property does a single digital read.
"""
import digitalio
import time


class Button:
    DEBOUNCE = 0.05  # 50ms debounce window

    def __init__(self, pin):
        self._io = digitalio.DigitalInOut(pin)
        self._io.switch_to_input(pull=digitalio.Pull.UP)
        self._last_state = True
        self._last_time = 0.0

    @property
    def pressed(self):
        """Return True once per press (falling-edge with debounce)."""
        now = time.monotonic()
        state = self._io.value
        if not state and self._last_state:
            if now - self._last_time > self.DEBOUNCE:
                self._last_time = now
                self._last_state = state
                return True
        self._last_state = state
        return False
