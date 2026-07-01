# =============================================================================
# settings.py
# User-configurable settings for the monitoring system.
#
# Settings are now saved to flash (or, on PC, a local JSON file) through
# persistence.py, so they survive a reboot. On first boot, or if the saved
# file is missing or corrupted, the system falls back to the defaults below.
# =============================================================================

import persistence


# ---------------------------------------------------------------------------
# Where settings are saved. On the ESP32 this lives on the flash filesystem
# alongside main.py. On PC it is a plain JSON file in the project folder.
# ---------------------------------------------------------------------------
_SETTINGS_FILE = "settings_store.json"


# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

_DEFAULTS = {
    # Daily water usage limit set by the user (in litres)
    "daily_limit_litres": 100.0,

    # Warning threshold as a percentage of the daily limit (0-100).
    # The dashboard shows a warning when usage crosses this percentage.
    "warning_threshold_pct": 80.0,

    # How many seconds a moisture node must stay continuously wet before
    # the system escalates from "leak_alarm" to "confirmed_leak".
    "confirmed_leak_threshold_sec": 300,
}


def _load_from_storage():
    """
    Load settings from flash/disk on startup. Any keys missing from the
    saved file fall back to defaults, and any unknown keys in the saved
    file are ignored. This keeps old saved files compatible even after
    new settings are added.

    Returns:
        dict: settings dictionary, merged with defaults
    """
    stored = persistence.load_json(_SETTINGS_FILE, None)
    merged = dict(_DEFAULTS)
    if isinstance(stored, dict):
        for key in _DEFAULTS:
            if key in stored:
                merged[key] = stored[key]
    return merged


_settings = _load_from_storage()


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
    Update one or more settings values and save them to flash/disk.
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
    persistence.save_json(_SETTINGS_FILE, _settings)
    return get_settings()


def reset_settings_to_defaults():
    """
    Reset settings back to defaults and save that to flash/disk.
    Used by tests, and available to the dashboard as a "factory reset"
    style action if needed later.
    """
    global _settings
    _settings = dict(_DEFAULTS)
    persistence.save_json(_SETTINGS_FILE, _settings)
    return get_settings()


def get_daily_limit():
    """Convenience function: return the daily limit in litres."""
    return _settings["daily_limit_litres"]


def get_warning_threshold():
    """Convenience function: return the warning threshold percentage."""
    return _settings["warning_threshold_pct"]


def get_confirmed_leak_threshold_sec():
    """Convenience function: return the confirmed-leak escalation time."""
    return _settings["confirmed_leak_threshold_sec"]
