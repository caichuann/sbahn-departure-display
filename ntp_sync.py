"""
NTP time synchronization state machine.
Uses adafruit_ntp for time sync, with non-blocking retry logic.
"""
import time
import rtc
import adafruit_ntp
from settings import NTP_RETRY_SEC, NTP_CACHE_SECONDS


MAX_STARTUP_ATTEMPTS = 3   # outer retries (3 × 5 inner = 15 total NTP tries)

# ── States ─────────────────────────────────────────────────────────
(
    S_IDLE,      # Not yet synced (initial)
    S_SYNCING,   # NTP request in progress
    S_SYNCED,    # Time is valid
    S_ERROR,     # Sync failed, waiting to retry
) = range(4)

# ── Time zone helpers ──────────────────────────────────────────────
def _day_of_week(y, m, d):
    """Calculate day of week (0=Sunday)."""
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if m < 3:
        y -= 1
    return (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7


def _is_dst(utctime):
    """Check if Central European DST is active."""
    mo, d, h, y = utctime.tm_mon, utctime.tm_mday, utctime.tm_hour, utctime.tm_year
    if mo < 3 or mo > 10:
        return False
    if 3 < mo < 10:
        return True
    last_sunday = 31 - _day_of_week(y, mo, 31)
    if mo == 3:
        return d > last_sunday or (d == last_sunday and h >= 1)
    else:
        return d < last_sunday or (d == last_sunday and h < 1)


def get_tz_offset():
    """Return current timezone offset from UTC (1 = CET, 2 = CEST)."""
    return 2 if _is_dst(time.localtime()) else 1


class NTPSync:
    def __init__(self, pool):
        self._pool = pool
        self.synced = False          # public
        self._state = S_IDLE
        self._last_sync = -9999.0
        self._attempt = 0
        self._next_retry = 0.0

    def sync_now(self):
        """Blocking initial NTP sync. Used only during startup.
        Returns True on success, False after max attempts.
        On failure the tick() state machine continues background retries."""
        print("Syncing NTP...")
        for outer in range(MAX_STARTUP_ATTEMPTS):
            for attempt in range(5):
                try:
                    ntp = adafruit_ntp.NTP(
                        self._pool, tz_offset=0, cache_seconds=NTP_CACHE_SECONDS)
                    rtc.RTC().datetime = ntp.datetime
                    self.synced = True
                    self._last_sync = time.monotonic()
                    self._state = S_SYNCED
                    u = time.localtime()
                    tz = get_tz_offset()
                    print(f"NTP OK UTC {u.tm_hour:02d}:{u.tm_min:02d} TZ+{tz}h")
                    return True
                except Exception as e:
                    print(f"NTP attempt {outer * 5 + attempt + 1}: {e}")
                    time.sleep(2)
            if outer < MAX_STARTUP_ATTEMPTS - 1:
                print(f"NTP outer retry {outer + 1}/{MAX_STARTUP_ATTEMPTS}...")
                time.sleep(NTP_RETRY_SEC)
        print("NTP: giving up after max attempts, will retry in background")
        self._state = S_ERROR
        self._next_retry = time.monotonic() + NTP_RETRY_SEC
        return False

    def tick(self):
        """
        Non-blocking tick. Re-syncs periodically.
        Returns True if time is considered valid.
        """
        now = time.monotonic()

        if self._state == S_IDLE:
            # Should not happen after startup, but handle gracefully
            self._state = S_SYNCING

        elif self._state == S_SYNCING:
            try:
                ntp = adafruit_ntp.NTP(
                    self._pool, tz_offset=0, cache_seconds=NTP_CACHE_SECONDS)
                rtc.RTC().datetime = ntp.datetime
                self.synced = True
                self._last_sync = now
                self._state = S_SYNCED
                self._attempt = 0
            except Exception as e:
                self._attempt += 1
                if self._attempt >= 3:
                    print(f"NTP sync failed: {e}")
                    self._state = S_ERROR
                    self._next_retry = now + NTP_RETRY_SEC
                # else: stay in SYNCING, retry next tick

        elif self._state == S_SYNCED:
            if now - self._last_sync >= NTP_CACHE_SECONDS:
                self._state = S_SYNCING

        elif self._state == S_ERROR:
            if now >= self._next_retry:
                self._attempt = 0
                self._state = S_SYNCING

        return self.synced

    def get_local_time(self):
        """Return (hour, minute) adjusted for timezone."""
        utc = time.localtime()
        tz = get_tz_offset()
        h = (utc.tm_hour + tz) % 24
        return h, utc.tm_min
