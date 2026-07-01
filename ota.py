# =============================================================================
# ota.py
# Over-the-air firmware updates.
#
# IMPORTANT LIMITATION: this is a simple file-overwrite updater, not a true
# dual-partition OTA scheme. It downloads new .py files from URLs listed in
# a manifest and writes them directly over the existing files on flash,
# then reboots. This is enough to push bug fixes and new modules to a
# device in the field, but it has no rollback safety: if a downloaded file
# is bad, or power is lost mid-write, the device may fail to boot until it
# is reflashed over USB. A production system would use the ESP32's
# partition table (esp32.Partition) to write the new firmware to an
# inactive slot and only switch over after verifying it booted correctly.
# That is a reasonable next step but is out of scope for this module.
#
# Manifest format (a JSON document, fetched from a URL you control):
#   {
#     "version": "0.2.0",
#     "files": {
#       "classification.py": "https://example.com/fw/0.2.0/classification.py",
#       "settings.py": "https://example.com/fw/0.2.0/settings.py"
#     }
#   }
# =============================================================================

import persistence

try:
    import urequests as requests_lib
    _HAS_REQUESTS = True
except ImportError:
    try:
        import requests as requests_lib
        _HAS_REQUESTS = True
    except ImportError:
        _HAS_REQUESTS = False


_VERSION_FILE = "ota_version.json"
_DEFAULT_VERSION = "0.1.0"


def get_current_version():
    """Return the version string of the firmware currently installed."""
    stored = persistence.load_json(_VERSION_FILE, {"version": _DEFAULT_VERSION})
    return stored.get("version", _DEFAULT_VERSION)


def _set_current_version(version):
    persistence.save_json(_VERSION_FILE, {"version": version})


def _version_tuple(version_str):
    """Turn '1.2.3' into (1, 2, 3) so versions can be compared numerically."""
    parts = []
    for part in version_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_update_available(manifest):
    """
    Compare a manifest's version against the currently installed version.

    Args:
        manifest (dict): a manifest dict with at least a "version" key

    Returns:
        bool: True if the manifest's version is newer
    """
    current = _version_tuple(get_current_version())
    candidate = _version_tuple(manifest.get("version", "0.0.0"))
    return candidate > current


def fetch_manifest(manifest_url):
    """
    Download and parse a manifest JSON document from a URL.

    Args:
        manifest_url (str): URL to the manifest

    Returns:
        dict or None: the parsed manifest, or None on any failure
    """
    if not _HAS_REQUESTS:
        return None
    try:
        response = requests_lib.get(manifest_url)
        try:
            data = response.json()
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        return data
    except Exception as e:
        print("[ota] Failed to fetch manifest: {}".format(e))
        return None


def apply_update(manifest):
    """
    Download every file listed in the manifest and overwrite the matching
    local file, then record the new version number. Does not reboot the
    device; the caller decides when it is safe to do that (typically right
    after this returns success, outside of an active request handler).

    Args:
        manifest (dict): a manifest dict as returned by fetch_manifest()

    Returns:
        dict: {"applied": bool, "reason": str, "files_written": list}
    """
    files = manifest.get("files", {})
    if not files:
        return {"applied": False, "reason": "manifest has no files listed", "files_written": []}

    if not _HAS_REQUESTS:
        return {"applied": False, "reason": "no http library available", "files_written": []}

    written = []
    try:
        for local_name, url in files.items():
            response = requests_lib.get(url)
            try:
                content = response.text
            finally:
                close = getattr(response, "close", None)
                if close:
                    close()
            with open(local_name, "w") as f:
                f.write(content)
            written.append(local_name)

        _set_current_version(manifest.get("version", get_current_version()))
        return {"applied": True, "reason": "ok", "files_written": written}

    except Exception as e:
        return {
            "applied": False,
            "reason": "failed partway through: {}".format(e),
            "files_written": written,
        }


def reboot():
    """
    Restart the device to load the newly written files. On MicroPython
    this calls machine.reset(). On PC there is no equivalent, so this just
    logs what would happen, since a PC test server should not actually
    exit out from under the test suite.
    """
    try:
        import machine
        machine.reset()
    except ImportError:
        print("[ota] reboot() called on PC; on the ESP32 this would call machine.reset()")
