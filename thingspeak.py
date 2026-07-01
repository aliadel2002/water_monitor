# =============================================================================
# thingspeak.py
# Optional cloud logging to ThingSpeak.
#
# ThingSpeak channels accept updates as a simple HTTP GET or POST with an
# API key and up to eight numbered fields. This module maps our state onto
# three of those fields:
#
#   field1 = flow_rate_lpm
#   field2 = daily_total_litres
#   field3 = a numeric code for system_state (0=normal, 1=warning,
#            2=abnormal, 3=leak_alarm, 4=confirmed_leak)
#
# Cloud logging is off by default. It only activates once the user enables
# it and provides an API key through the dashboard, and every network call
# is wrapped so that a missing network, a bad key, or an unreachable
# ThingSpeak server never crashes the calling background task, it just
# skips that push and tries again next interval.
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


_CONFIG_FILE = "thingspeak_config.json"

_DEFAULT_CONFIG = {
    "enabled": False,
    "api_key": "",
    "update_interval_sec": 60,
}

_STATE_CODES = {
    "normal": 0,
    "warning": 1,
    "abnormal": 2,
    "leak_alarm": 3,
    "confirmed_leak": 4,
}


def _load_config():
    stored = persistence.load_json(_CONFIG_FILE, None)
    merged = dict(_DEFAULT_CONFIG)
    if isinstance(stored, dict):
        for key in _DEFAULT_CONFIG:
            if key in stored:
                merged[key] = stored[key]
    return merged


_config = _load_config()


def get_config():
    """Return a copy of the current ThingSpeak configuration."""
    return dict(_config)


def update_config(new_values):
    """
    Update the ThingSpeak configuration (enabled, api_key,
    update_interval_sec) and save it to flash/disk.

    Args:
        new_values (dict): any subset of the config keys

    Returns:
        dict: the updated configuration
    """
    for key in _DEFAULT_CONFIG:
        if key in new_values:
            _config[key] = new_values[key]
    persistence.save_json(_CONFIG_FILE, _config)
    return get_config()


def push_update(state):
    """
    Send one update to ThingSpeak, if cloud logging is enabled and
    configured. This never raises; every failure mode returns a result
    dict describing what happened instead, so a background task can call
    this every interval without a try/except of its own.

    Args:
        state (dict): a state dictionary as returned by
                       sensor_state.get_active_state()

    Returns:
        dict: {"sent": bool, "reason": str}
    """
    if not _config["enabled"]:
        return {"sent": False, "reason": "cloud logging disabled"}

    if not _config["api_key"]:
        return {"sent": False, "reason": "no api key configured"}

    if not _HAS_REQUESTS:
        return {"sent": False, "reason": "no http library available on this platform"}

    field3 = _STATE_CODES.get(state.get("system_state"), -1)

    url = (
        "https://api.thingspeak.com/update"
        "?api_key={}&field1={}&field2={}&field3={}"
    ).format(
        _config["api_key"],
        state.get("flow_rate_lpm", 0.0),
        state.get("daily_total_litres", 0.0),
        field3,
    )

    try:
        response = requests_lib.get(url)
        try:
            ok = response.status_code == 200
        finally:
            # MicroPython's urequests response must be closed to free
            # the underlying socket, which CPython's requests does not
            # require but also does not error on.
            close = getattr(response, "close", None)
            if close:
                close()
        if ok:
            return {"sent": True, "reason": "ok"}
        return {"sent": False, "reason": "http status {}".format(response.status_code)}
    except Exception as e:
        return {"sent": False, "reason": str(e)}
