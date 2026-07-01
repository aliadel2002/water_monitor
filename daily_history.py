# =============================================================================
# daily_history.py
# Detects when a new day has started and archives the previous day's water
# usage total, then resets the running daily total so it starts counting
# from zero again.
#
# Only the real sensor state is tracked here. Test mode totals are meant to
# be thrown away when you exit test mode or reset test state, so they are
# never archived.
#
# History is capped at MAX_HISTORY_DAYS entries, oldest dropped first, and
# is saved to flash/disk through persistence.py so it survives a reboot.
# =============================================================================

import clock
import persistence
import sensor_state
import event_log


_HISTORY_FILE = "daily_history.json"
MAX_HISTORY_DAYS = 30


def _load():
    """Load the stored history and the last-seen date from disk/flash."""
    return persistence.load_json(_HISTORY_FILE, {"last_date": None, "entries": []})


def _save(data):
    """Save the history and last-seen date to disk/flash."""
    persistence.save_json(_HISTORY_FILE, data)


_state = _load()


def get_history(n=None):
    """
    Return the stored history entries, oldest first.

    Args:
        n (int, optional): if given, only the most recent n entries

    Returns:
        list: entries of {"date": "YYYY-MM-DD", "total_litres": float}
    """
    entries = _state["entries"]
    if n is not None:
        return entries[-n:]
    return list(entries)


def check_and_roll_over():
    """
    Compare today's date against the last date we recorded. If the date has
    changed, archive the real state's daily total under yesterday's date
    and reset the real state's daily total to zero for the new day.

    This is called periodically (see server.py / server_pc.py) rather than
    on a fixed schedule, since MicroPython does not have a full cron-style
    scheduler. Checking every minute or so is frequent enough to catch the
    day boundary without meaningfully delaying the rollover.

    Returns:
        bool: True if a rollover happened, False if it is still the same day
    """
    today_str = clock.today()
    last_date = _state["last_date"]

    # First run ever: just record today's date, nothing to archive yet.
    if last_date is None:
        _state["last_date"] = today_str
        _save(_state)
        return False

    # Still the same day, nothing to do.
    if last_date == today_str:
        return False

    # The date has changed. Archive yesterday's total before resetting it.
    yesterday_total = sensor_state.REAL_STATE["daily_total_litres"]
    _state["entries"].append({"date": last_date, "total_litres": yesterday_total})

    # Keep only the most recent MAX_HISTORY_DAYS entries.
    if len(_state["entries"]) > MAX_HISTORY_DAYS:
        _state["entries"] = _state["entries"][-MAX_HISTORY_DAYS:]

    _state["last_date"] = today_str
    _save(_state)

    # Reset the running total for the new day.
    sensor_state.REAL_STATE["daily_total_litres"] = 0.0

    event_log.add_event(
        "Daily total for {} archived at {:.1f} L, counter reset for {}".format(
            last_date, yesterday_total, today_str
        )
    )
    return True


def reset_history():
    """
    Clear all stored history. Used by tests to start from a clean slate,
    and available as a manual reset if the user wants to clear their
    usage history from the dashboard.
    """
    global _state
    _state = {"last_date": clock.today(), "entries": []}
    _save(_state)
