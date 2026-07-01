# =============================================================================
# event_log.py
# In-memory event log for the monitoring system.
#
# Events are stored as a list of dictionaries. Each entry has a message
# and a sequence number. Timestamps are NOT added here. The dashboard
# polls GET /api/events every 3 seconds and stamps each event with the
# browser's local clock when it renders it. There is no WebSocket
# connection in this system, only plain polling over fetch(). Keeping
# timestamps out of the server avoided needing NTP or RTC setup early on;
# now that ntp_sync.py exists, the server does know the correct time, but
# events are still left unstamped here so the dashboard's display logic
# does not need to change.
#
# The log is capped at MAX_ENTRIES to prevent unbounded memory growth.
# When the cap is reached, the oldest entry is dropped.
# =============================================================================


# Maximum number of events to keep in memory at any time
MAX_ENTRIES = 50

# The log itself — list of dicts: {"id": int, "message": str}
_log = []

# Auto-incrementing event ID counter
_event_counter = 0


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def add_event(message):
    """
    Append a new event to the log.
    If the log is at capacity, the oldest entry is removed first.

    Args:
        message (str): human-readable description of the event
    """
    global _event_counter
    _event_counter += 1

    entry = {
        "id":      _event_counter,
        "message": message,
    }

    _log.append(entry)

    # Enforce the cap
    if len(_log) > MAX_ENTRIES:
        _log.pop(0)


def get_all_events():
    """
    Return a copy of all events in the log, newest last.
    Returns a copy so callers cannot mutate the internal list.
    """
    return list(_log)


def get_recent_events(n=10):
    """
    Return the n most recent events.

    Args:
        n (int): number of events to return (default 10)

    Returns:
        list: up to n most recent event dictionaries
    """
    return _log[-n:] if len(_log) >= n else list(_log)


def clear_log():
    """Clear all events from the log. Used when resetting the system."""
    global _log, _event_counter
    _log = []
    _event_counter = 0
