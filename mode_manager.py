"""
Tracks the current display mode and provides clean switching interface.
Replaces the scattered `current_mode` variable from the original code.
"""
from settings import MODE_NAMES, MODE_MAIN


class ModeManager:
    def __init__(self, initial_mode=MODE_MAIN):
        self.mode = initial_mode

    def set(self, new_mode):
        """Set mode. Returns True if mode actually changed."""
        new_mode = new_mode % len(MODE_NAMES)
        if new_mode != self.mode:
            self.mode = new_mode
            return True
        return False

    def cycle(self, direction):
        """Cycle mode by +1 or -1."""
        return self.set((self.mode + direction) % len(MODE_NAMES))

    @property
    def name(self):
        return MODE_NAMES[self.mode]

    @property
    def is_main(self):
        return self.mode == MODE_MAIN

    @property
    def is_game(self):
        return self.mode == MODE_GAME
