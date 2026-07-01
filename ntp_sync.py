# =============================================================================
# ntp_sync.py
# Time synchronization for the hub.
#
# The ESP32 has no battery-backed real-time clock, so on every power loss
# its clock resets to a meaningless default. MicroPython ships a built-in
# "ntptime" module that fetches the correct time over the network and sets
# the device's clock from it, which is what this module uses on-device.
#
# On PC, the operating system's clock is already correct, so sync() there
# is a no-op that just reports success. This keeps server.py and
# server_pc.py able to call the same function without checking which
# platform they are on.
# =============================================================================

import clock

try:
    import ntptime
    _HAS_NTPTIME = True
except ImportError:
    _HAS_NTPTIME = False


_status = {
    "synced": False,
    "last_sync_time": None,
    "last_error": None,
    "source": "ntp" if _HAS_NTPTIME else "system_clock",
}


def sync():
    """
    Attempt to synchronize the clock.

    On the ESP32 (ntptime available), this reaches out to an NTP server and
    sets the device's real-time clock from the response. On PC, there is
    nothing to do since the OS clock is already correct, so this simply
    records a successful sync.

    Returns:
        bool: True if the clock is considered synced, False if the NTP
              request failed (device only; PC always returns True)
    """
    if not _HAS_NTPTIME:
        _status["synced"] = True
        _status["last_sync_time"] = clock.now()
        _status["last_error"] = None
        return True

    try:
        ntptime.settime()
        _status["synced"] = True
        _status["last_sync_time"] = clock.now()
        _status["last_error"] = None
        return True
    except Exception as e:
        _status["synced"] = False
        _status["last_error"] = str(e)
        return False


def get_status():
    """
    Return the current sync status for the dashboard or API.

    Returns:
        dict: synced (bool), last_sync_time (float or None),
              last_error (str or None), source ("ntp" or "system_clock")
    """
    return dict(_status)
