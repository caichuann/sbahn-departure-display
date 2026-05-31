"""
Chrome Dino Game for 64x64 MatrixPortal display.
Non-blocking cooperative multitasking — tick() advances one frame.
Jump commands come from the web server via the jump() method.

Renders to a single 64x64 displayio.Bitmap with 3-color palette,
wrapped in a TileGrid for compatibility with DisplayManager.
"""
import random
import displayio

# ── Game constants ─────────────────────────────────────────────
GROUND_Y = 55               # ground line y-position
DINO_X = 6                  # dino fixed x-position
GRAVITY = 0.6               # pixels per frame²
JUMP_VELOCITY = -4.3        # initial jump velocity (px/frame)
GAME_SPEED_INITIAL = 1.2    # starting scroll speed
GAME_SPEED_MAX = 3.5        # max scroll speed
GAME_SPEED_INCREMENT = 0.0004  # speed increase per frame
OBSTACLE_INTERVAL_MIN = 40  # min frames between spawns
OBSTACLE_INTERVAL_MAX = 85  # max frames between spawns

# ── Dino sprites (8 wide x 10 tall) ────────────────────────────
DINO_W, DINO_H = 8, 10

DINO_RUN1 = bytes([   # legs apart
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 0, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 0, 0, 1, 1,
    0, 0, 1, 1, 0, 0, 1, 1,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 0, 1, 1,
])

DINO_RUN2 = bytes([   # legs together
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 0, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 0, 0, 1, 1,
    0, 0, 1, 1, 0, 1, 1, 1,
    0, 0, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 1, 1, 0, 0, 0,
    0, 0, 0, 1, 1, 1, 0, 0,
])

DINO_JUMP = bytes([   # legs tucked
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 0, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 0, 0, 1, 0, 0,
    0, 0, 1, 1, 1, 1, 0, 0,
    0, 0, 0, 1, 1, 0, 0, 0,
])

DINO_DEAD = bytes([   # X_X eyes
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 0, 0, 0, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 0,
    0, 0, 1, 0, 0, 0, 1, 0,
    0, 1, 0, 1, 0, 1, 0, 0,
    0, 0, 0, 1, 1, 1, 0, 0,
    0, 0, 1, 0, 0, 1, 0, 0,
    0, 1, 0, 0, 0, 0, 1, 0,
])

# ── Cactus sprites ────────────────────────────────────────────
CACTUS_W, CACTUS_H = 4, 7
CACTUS = bytes([
    0, 1, 1, 0,
    1, 1, 1, 0,
    1, 1, 1, 1,
    1, 1, 1, 0,
    1, 1, 1, 0,
    1, 1, 1, 0,
    0, 1, 1, 0,
])

CACTUS_TALL_W, CACTUS_TALL_H = 6, 9
CACTUS_TALL = bytes([
    0, 0, 1, 1, 0, 0,
    0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
    1, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 0,
])

# ── Bird sprite (8 wide x 6 tall) ─────────────────────────────
BIRD_W, BIRD_H = 8, 6
BIRD1 = bytes([   # wings up
    0, 0, 0, 0, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 1, 1,
    0, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 0, 0, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
])
BIRD2 = bytes([   # wings down
    0, 0, 0, 0, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 1,
    0, 0, 0, 1, 1, 1, 1, 1,
    0, 0, 0, 0, 1, 1, 1, 0,
    0, 0, 0, 0, 0, 0, 0, 0,
])

# ── 3x5 pixel font ────────────────────────────────────────────
_FONT = {
    'A': (1,1,1, 1,0,1, 1,1,1, 1,0,1, 1,0,1),
    'B': (1,1,0, 1,0,1, 1,1,0, 1,0,1, 1,1,0),
    'C': (1,1,1, 1,0,0, 1,0,0, 1,0,0, 1,1,1),
    'D': (1,1,0, 1,0,1, 1,0,1, 1,0,1, 1,1,0),
    'E': (1,1,1, 1,0,0, 1,1,1, 1,0,0, 1,1,1),
    'G': (1,1,1, 1,0,0, 1,0,1, 1,0,1, 1,1,1),
    'H': (1,0,1, 1,0,1, 1,1,1, 1,0,1, 1,0,1),
    'I': (1,1,1, 0,1,0, 0,1,0, 0,1,0, 1,1,1),
    'M': (1,0,1, 1,1,1, 1,0,1, 1,0,1, 1,0,1),
    'N': (1,0,1, 1,1,1, 1,1,1, 1,0,1, 1,0,1),
    'O': (1,1,1, 1,0,1, 1,0,1, 1,0,1, 1,1,1),
    'P': (1,1,1, 1,0,1, 1,1,1, 1,0,0, 1,0,0),
    'R': (1,1,0, 1,0,1, 1,1,0, 1,0,1, 1,0,1),
    'S': (1,1,1, 1,0,0, 1,1,1, 0,0,1, 1,1,1),
    'T': (1,1,1, 0,1,0, 0,1,0, 0,1,0, 0,1,0),
    'U': (1,0,1, 1,0,1, 1,0,1, 1,0,1, 1,1,1),
    'V': (1,0,1, 1,0,1, 1,0,1, 0,1,0, 0,1,0),
    'Y': (1,0,1, 1,0,1, 1,1,1, 0,0,1, 1,1,1),
}

_DIGITS = {
    0: (1,1,1, 1,0,1, 1,0,1, 1,0,1, 1,1,1),
    1: (0,1,0, 1,1,0, 0,1,0, 0,1,0, 1,1,1),
    2: (1,1,1, 0,0,1, 1,1,1, 1,0,0, 1,1,1),
    3: (1,1,1, 0,0,1, 1,1,1, 0,0,1, 1,1,1),
    4: (1,0,1, 1,0,1, 1,1,1, 0,0,1, 0,0,1),
    5: (1,1,1, 1,0,0, 1,1,1, 0,0,1, 1,1,1),
    6: (1,1,1, 1,0,0, 1,1,1, 1,0,1, 1,1,1),
    7: (1,1,1, 0,0,1, 0,0,1, 0,1,0, 0,1,0),
    8: (1,1,1, 1,0,1, 1,1,1, 1,0,1, 1,1,1),
    9: (1,1,1, 1,0,1, 1,1,1, 0,0,1, 1,1,1),
}


class DinoGame:
    """Chrome Dino mini-game rendered to 64x64 displayio.Bitmap."""

    def __init__(self):
        self.bitmap = None
        self.palette = None
        self.tilegrid = None

        # Mutable game state
        self._dino_y = 0.0
        self._dino_vy = 0.0
        self._is_jumping = False
        self._obstacles = []          # [x, y, w, h, type_str]
        self._score = 0
        self._hi_score = 0
        self._speed = GAME_SPEED_INITIAL
        self._state = "idle"          # idle | playing | over
        self._spawn_timer = 0
        self._anim_frame = 0          # 0 or 1 for sprite animation
        self._anim_counter = 0
        self._ground_offset = 0.0

        # Jump request from web server (set via jump())
        self._jump_pending = False

    # ── Public interface ───────────────────────────────────────
    def make_tilegrid(self):
        """Create and return the TileGrid for display."""
        self.palette = displayio.Palette(3)
        self.palette[0] = 0x000000   # black background
        self.palette[1] = 0xFFFFFF   # white foreground
        self.palette[2] = 0x222222   # dim gray (ground texture)

        self.bitmap = displayio.Bitmap(64, 64, 3)
        self.tilegrid = displayio.TileGrid(
            self.bitmap, pixel_shader=self.palette)
        self._reset_state()
        return self.tilegrid

    def reset(self):
        """Reset game to idle. Called when switching into game mode."""
        self._reset_state()

    def jump(self):
        """Request a jump. Called from web server /jump endpoint."""
        self._jump_pending = True

    def tick(self):
        """Advance game state by one frame. Call every loop iteration."""
        if self.bitmap is None:
            return

        if self._state == "idle":
            self._tick_idle()
        elif self._state == "playing":
            self._tick_playing()
        elif self._state == "over":
            self._tick_over()

    # ── Internal state ─────────────────────────────────────────
    def _reset_state(self):
        ground_level = GROUND_Y - DINO_H
        self._dino_y = float(ground_level)
        self._dino_vy = 0.0
        self._is_jumping = False
        self._obstacles = []
        self._score = 0
        self._speed = GAME_SPEED_INITIAL
        self._state = "idle"
        self._spawn_timer = 30
        self._anim_frame = 0
        self._anim_counter = 0
        self._ground_offset = 0.0
        self._jump_pending = False

    def _do_jump(self):
        self._dino_vy = JUMP_VELOCITY
        self._is_jumping = True

    # ── Tick: idle ─────────────────────────────────────────────
    def _tick_idle(self):
        if self._jump_pending:
            self._jump_pending = False
            self._state = "playing"
            self._do_jump()
            return

        # Gentle idle animation
        self._anim_counter += 1
        if self._anim_counter >= 15:
            self._anim_counter = 0
            self._anim_frame = (self._anim_frame + 1) % 2

        self._clear()
        self._draw_ground()
        dino_sprite = DINO_RUN1 if self._anim_frame == 0 else DINO_RUN2
        self._draw_sprite(DINO_X, int(self._dino_y),
                          dino_sprite, DINO_W, DINO_H)
        self._draw_text_centered(32, 28, "TAP TO")
        self._draw_text_centered(32, 40, "START")

    # ── Tick: playing ──────────────────────────────────────────
    def _tick_playing(self):
        # Jump input
        if self._jump_pending:
            self._jump_pending = False
            if not self._is_jumping:
                self._do_jump()

        # Physics
        if self._is_jumping:
            self._dino_y += self._dino_vy
            self._dino_vy += GRAVITY
            ground_level = GROUND_Y - DINO_H
            if self._dino_y >= ground_level:
                self._dino_y = float(ground_level)
                self._dino_vy = 0.0
                self._is_jumping = False

        # Move obstacles left
        for obs in self._obstacles:
            obs[0] -= self._speed

        # Remove off-screen obstacles, tally score
        survived = []
        for obs in self._obstacles:
            if obs[0] + obs[2] > 0:
                survived.append(obs)
            else:
                self._score += 1
        self._obstacles = survived

        # Spawn new obstacle when timer expires
        self._spawn_timer -= 1
        if self._spawn_timer <= 0:
            self._spawn_obstacle()
            base = OBSTACLE_INTERVAL_MIN + random.randint(
                0, OBSTACLE_INTERVAL_MAX - OBSTACLE_INTERVAL_MIN)
            self._spawn_timer = max(18, base - self._score // 3)

        # Gradual speed increase
        self._speed = min(GAME_SPEED_MAX,
                          self._speed + GAME_SPEED_INCREMENT)

        # Animation counter
        self._anim_counter += 1
        if self._anim_counter >= 5:
            self._anim_counter = 0
            self._anim_frame = (self._anim_frame + 1) % 2

        # Ground scroll offset
        self._ground_offset = (self._ground_offset + self._speed) % 12.0

        # Collision detection
        dino_y_int = int(self._dino_y)
        for obs in self._obstacles:
            if self._check_collision(int(obs[0]), obs[1],
                                     obs[2], obs[3], dino_y_int):
                self._state = "over"
                if self._score > self._hi_score:
                    self._hi_score = self._score
                return

        # ── Render ──
        self._clear()
        self._draw_ground()
        for obs in self._obstacles:
            self._draw_obstacle(obs)

        if self._is_jumping:
            dino_sprite = DINO_JUMP
        elif self._anim_frame == 0:
            dino_sprite = DINO_RUN1
        else:
            dino_sprite = DINO_RUN2

        self._draw_sprite(DINO_X, dino_y_int,
                          dino_sprite, DINO_W, DINO_H)
        self._draw_score(self._score)

    # ── Tick: over ─────────────────────────────────────────────
    def _tick_over(self):
        if self._jump_pending:
            self._jump_pending = False
            self._reset_state()
            self._state = "playing"
            self._do_jump()
            return

        self._clear()
        self._draw_ground()
        self._draw_sprite(DINO_X, int(self._dino_y),
                          DINO_DEAD, DINO_W, DINO_H)
        self._draw_score_display(self._score, 32 - 2 * 4, 24)
        self._draw_text_centered(32, 36, "TAP TO")
        self._draw_text_centered(32, 48, "RETRY")

    # ── Obstacle spawning ──────────────────────────────────────
    def _spawn_obstacle(self):
        r = random.randint(0, 255)
        if r < 40 and self._score > 100:
            # Bird at varying height
            bird_y = GROUND_Y - DINO_H - 6 - random.randint(0, 8)
            self._obstacles.append(
                [64.0, bird_y, BIRD_W, BIRD_H, "bird"])
        elif r < 160:
            # Tall cactus
            self._obstacles.append(
                [64.0, GROUND_Y - CACTUS_TALL_H,
                 CACTUS_TALL_W, CACTUS_TALL_H, "cactus_tall"])
        else:
            # Small cactus
            self._obstacles.append(
                [64.0, GROUND_Y - CACTUS_H,
                 CACTUS_W, CACTUS_H, "cactus"])

    def _draw_obstacle(self, obs):
        ox = int(obs[0])
        oy = obs[1]
        otype = obs[4]
        if otype == "bird":
            sprite = BIRD1 if self._anim_frame == 0 else BIRD2
            self._draw_sprite(ox, oy, sprite, BIRD_W, BIRD_H)
        elif otype == "cactus_tall":
            self._draw_sprite(ox, oy, CACTUS_TALL,
                              CACTUS_TALL_W, CACTUS_TALL_H)
        else:
            self._draw_sprite(ox, oy, CACTUS, CACTUS_W, CACTUS_H)

    # ── Collision ──────────────────────────────────────────────
    def _check_collision(self, ox, oy, ow, oh, dy):
        """AABB collision with 1px margin for forgiving gameplay."""
        margin = 1
        return (DINO_X + DINO_W - margin > ox + margin and
                DINO_X + margin < ox + ow - margin and
                dy + DINO_H - margin > oy + margin and
                dy + margin < oy + oh - margin)

    # ── Drawing primitives ─────────────────────────────────────
    def _clear(self):
        self.bitmap.fill(0)

    def _draw_sprite(self, x, y, sprite, w, h):
        """Blit a sprite onto the bitmap at (x, y)."""
        bmp = self.bitmap
        for row in range(h):
            py = y + row
            if py < 0 or py >= 64:
                continue
            for col in range(w):
                px = x + col
                if px < 0 or px >= 64:
                    continue
                if sprite[row * w + col]:
                    bmp[px, py] = 1

    def _draw_ground(self):
        """Draw the ground line and scrolling texture."""
        bmp = self.bitmap
        # Ground line (solid, full width)
        for x in range(64):
            bmp[x, GROUND_Y] = 1
        # Scrolling ground texture
        offset = int(self._ground_offset)
        for x in range(64):
            gx = (x + offset) % 12
            if gx in (1, 2, 7, 8):
                # Solid dim columns
                for y in range(GROUND_Y + 1, 64):
                    bmp[x, y] = 2
            elif gx == 4:
                # Dotted dim column
                for y in range(GROUND_Y + 1, 64):
                    if (y - GROUND_Y) % 3 == 0:
                        bmp[x, y] = 2

    # ── Score display ──────────────────────────────────────────
    def _draw_score(self, score):
        """Draw score right-aligned at top-right."""
        self._draw_score_display(score, 58, 2)

    def _draw_score_display(self, value, right_x, y):
        """Draw a number right-aligned with right edge at right_x."""
        if value == 0:
            digits = [0]
        else:
            digits = []
            v = value
            while v > 0:
                digits.append(v % 10)
                v //= 10
            digits.reverse()
        x = right_x
        for d in reversed(digits):
            x -= 4  # 3px digit + 1px gap
            self._draw_digit(x, y, d)

    def _draw_digit(self, x, y, digit):
        """Draw a single 3x5 digit at (x, y)."""
        data = _DIGITS.get(digit, _DIGITS[0])
        bmp = self.bitmap
        for row in range(5):
            for col in range(3):
                if data[row * 3 + col]:
                    px, py = x + col, y + row
                    if 0 <= px < 64 and 0 <= py < 64:
                        bmp[px, py] = 1

    # ── Text drawing ───────────────────────────────────────────
    def _draw_text_centered(self, cx, y, text):
        """Draw uppercase text centered horizontally at (cx, y)."""
        total_w = len(text) * 4 - 1   # 3px char + 1px gap, no trailing gap
        start_x = cx - total_w // 2
        for i, ch in enumerate(text):
            if ch == ' ':
                continue
            self._draw_char(start_x + i * 4, y, ch)

    def _draw_char(self, x, y, ch):
        """Draw a single 3x5 character at (x, y)."""
        data = _FONT.get(ch)
        if data is None:
            return
        bmp = self.bitmap
        for row in range(5):
            for col in range(3):
                if data[row * 3 + col]:
                    px, py = x + col, y + row
                    if 0 <= px < 64 and 0 <= py < 64:
                        bmp[px, py] = 1
