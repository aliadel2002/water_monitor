# =============================================================================
# clock.py
# Single source of "current time" for the whole system.
#
# Both classification (confirmed leak timing) and daily_history (midnight
# rollover) need to know what time it is. Rather than have every module
# call time.time() directly, they all call clock.now() instead. This gives
# two benefits.
#
#   1. Tests can freeze or fast-forward time with set_override() instead of
#      calling time.sleep() for real minutes or hours.
#   2. If NTP sync later changes how the clock is set on the ESP32, only
#      this one file needs to know about it. Everything else just asks
#      clock.now() and clock.today() as before.
#
# On both MicroPython and CPython, time.time() and time.localtime() behave
# the same way for our purposes: time.time() returns seconds since an
# epoch, and time.localtime() breaks a timestamp into a year/month/day
# tuple. The absolute epoch does not matter here, only that the values are
# consistent and move forward.
# =============================================================================

import time


# When set, now() returns this value instead of the real clock. Used only
# by tests, so they can jump the clock forward without a real delay.
_override_seconds = None


def now():
    """
    Return the current time as seconds since the epoch.

    Returns:
        float: current time in seconds, or the test override if one is set
    """
    if _override_seconds is not None:
        return _override_seconds
    return time.time()


def today():
    """
    Return the current date as a "YYYY-MM-DD" string, based on now().

    Returns:
        str: date string, e.g. "2026-06-30"
    """
    t = time.localtime(now())
    year, month, day = t[0], t[1], t[2]
    return "%04d-%02d-%02d" % (year, month, day)


def set_override(seconds):
    """
    Force now() to return a fixed value. Used by tests to simulate time
    passing (for example, jumping forward past the confirmed-leak
    threshold, or across a midnight boundary) without a real delay.

    Args:
        seconds (float): the timestamp now() should return
    """
    global _override_seconds
    _override_seconds = seconds


def advance_override(delta_seconds):
    """
    Move the overridden clock forward by delta_seconds. Requires that
    set_override() was already called. Convenient for tests that want to
    simulate "5 minutes later" relative to whatever time they started at.

    Args:
        delta_seconds (float): how many seconds to move forward
    """
    global _override_seconds
    if _override_seconds is None:
        _override_seconds = time.time()
    _override_seconds += delta_seconds


def clear_override():
    """Remove the test override so now() reads the real clock again."""
    global _override_seconds
    _override_seconds = None
