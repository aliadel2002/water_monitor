# =============================================================================
# persistence.py
# Shared file-based storage for anything that needs to survive a reboot.
#
# Settings, daily history, and the ThingSpeak/OTA configuration all need to
# outlive a power cycle. On the ESP32 this writes to the flash filesystem
# (the same filesystem MicroPython uses for main.py itself). On the PC this
# writes a plain JSON file next to the other project files. The same code
# path works on both, since both platforms support open()/read()/write() on
# regular files; there is no separate "NVS" library involved.
#
# Every function here is defensive: a missing file, a corrupt file, or a
# full filesystem should never crash the caller. Callers get back a default
# value on any failure and can decide what to do next.
# =============================================================================

import json


def load_json(path, default):
    """
    Read and parse a JSON file. Returns default if the file does not exist
    or cannot be parsed, so a fresh device or a corrupted file behaves the
    same as "no data saved yet" rather than crashing the caller.

    Args:
        path (str): file path to read
        default: value to return if the file is missing or invalid

    Returns:
        the parsed JSON value, or default
    """
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    """
    Write a value to a JSON file, overwriting whatever was there before.

    Args:
        path (str): file path to write
        data: any JSON-serializable value

    Returns:
        bool: True if the write succeeded, False if it failed. A failure
              is logged but never raised, since a failed save should not
              take down the classifier or the web server.
    """
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        return True
    except OSError as e:
        print("[persistence] Failed to save {}: {}".format(path, e))
        return False


def delete_file(path):
    """
    Remove a stored file if it exists. Used mainly by tests to reset
    storage between runs. Missing files are treated as already deleted.

    Args:
        path (str): file path to remove
    """
    try:
        import os
        os.remove(path)
    except OSError:
        pass
