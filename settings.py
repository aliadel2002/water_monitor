# =============================================================================
# settings.py
# User-configurable settings for the monitoring system.
#
# Settings are stored in memory only (no flash persistence for now).
# They reset to defaults on reboot. Flash persistence can be added
# later using MicroPython's 'uos' and file I/O or an NVS-style approach.
# =============================================================================


# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

_settings = {
    # Daily water usage limit set by the user (in litres)
    "daily_limit_litres": 100.0,

    # Warning threshold as a percentage of the daily limit (0–100).
    # The dashboard shows a warning when usage crosses this percentage.
    "warning_threshold_pct": 80.0,
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_settings():
    """
    Return a copy of the current settings dictionary.
    Returns a copy so callers cannot accidentally mutate the internal state.
    """
    return dict(_settings)


def update_settings(new_values):
    """
    Update one or more settings values.
    Only keys that already exist in _settings are accepted; unknown keys
    are silently ignored to prevent accidental injection of invalid settings.

    Args:
        new_values (dict): dictionary of setting keys and their new values

    Returns:
        dict: the updated settings dictionary
    """
    for key, value in new_values.items():
        if key in _settings:
            _settings[key] = value
    return get_settings()


def get_daily_limit():
    """Convenience function — return the daily limit in litres."""
    return _settings["daily_limit_litres"]


def get_warning_threshold():
    """Convenience function — return the warning threshold percentage."""
    return _settings["warning_threshold_pct"]
