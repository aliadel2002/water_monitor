# =============================================================================
# api_routes.py
# All REST API route handlers for the web dashboard.
#
# Routes are grouped by function:
#   /api/state          - current sensor readings and system state (GET)
#   /api/settings       - read and update user settings (GET / POST)
#   /api/reset-alarm    - reset a leak alarm if sensors are dry (POST)
#   /api/mode           - switch between real and test mode (GET / POST)
#   /api/test/update    - update individual test state values (POST)
#   /api/test/scenario  - apply a preset test scenario (POST)
#   /api/test/reset     - reset test state to defaults (POST)
#   /api/events         - retrieve the event log (GET)
#   /api/events/clear   - clear the event log (POST)
#   /api/history        - retrieve archived daily usage totals (GET)
#   /api/analytics      - rolling average, eco score, and streak (GET)
#   /api/time/status    - current clock sync status (GET)
#   /api/time/sync      - manually trigger a clock sync (POST)
#   /api/cloud/status   - ThingSpeak configuration and availability (GET)
#   /api/cloud/settings - update ThingSpeak configuration (POST)
#   /api/cloud/push     - manually push one update to ThingSpeak (POST)
#   /api/ota/status     - current firmware version (GET)
#   /api/ota/check      - check a manifest URL for a newer version (POST)
#   /api/ota/apply      - download and apply a checked update (POST)
#   /api/ota/reboot     - restart the device after an applied update (POST)
#   /api/espnow/status  - ESP-NOW receiver availability and status (GET)
#
# Each handler is a plain function that accepts a MicroDot Request object
# and returns a tuple of (body, status_code, headers).
# =============================================================================

import json
import event_log
import sensor_state
import settings
import classification
import daily_history
import analytics
import ntp_sync
import thingspeak
import ota
import espnow_receiver


# ---------------------------------------------------------------------------
# Content-type header used on all JSON responses
# ---------------------------------------------------------------------------
JSON_HEADERS = {"Content-Type": "application/json"}


# ===========================================================================
# STATE
# ===========================================================================

def handle_get_state(request):
    """
    GET /api/state
    Return the currently active sensor state along with computed
    usage percentage and the current mode.
    """
    state = sensor_state.get_active_state()
    cfg   = settings.get_settings()

    # Compute usage percentage safely (avoid divide-by-zero)
    limit = cfg["daily_limit_litres"]
    usage_pct = (state["daily_total_litres"] / limit * 100) if limit > 0 else 0
    warn_thresh = cfg["warning_threshold_pct"]

    # usage_exceeded is independent of system_state — it flags that daily
    # consumption has crossed the warning threshold so the dashboard can show
    # a separate banner without affecting the leak/anomaly state machine.
    usage_exceeded = limit > 0 and usage_pct >= warn_thresh

    payload = {
        "mode":              sensor_state.get_mode(),
        "system_state":      state["system_state"],
        "flow_rate_lpm":     state["flow_rate_lpm"],
        "daily_total_litres": state["daily_total_litres"],
        "daily_limit_litres": limit,
        "usage_pct":         round(usage_pct, 1),
        "warning_threshold_pct": warn_thresh,
        "usage_exceeded":    usage_exceeded,
        "moisture_nodes":    state["moisture_nodes"],
        "acoustic_sensor":   state["acoustic_sensor"],
    }
    return json.dumps(payload), 200, JSON_HEADERS


# ===========================================================================
# SETTINGS
# ===========================================================================

def handle_get_settings(request):
    """
    GET /api/settings
    Return the current user settings.
    """
    return json.dumps(settings.get_settings()), 200, JSON_HEADERS


def handle_post_settings(request):
    """
    POST /api/settings
    Update one or more user settings. Expects a JSON body with any
    combination of: daily_limit_litres, warning_threshold_pct.

    Validates that:
      - daily_limit_litres is a positive number
      - warning_threshold_pct is between 1 and 99
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    # Validate daily limit
    if "daily_limit_litres" in body:
        val = body["daily_limit_litres"]
        if not isinstance(val, (int, float)) or val <= 0:
            return json.dumps({"error": "daily_limit_litres must be a positive number"}), 400, JSON_HEADERS

    # Validate warning threshold
    if "warning_threshold_pct" in body:
        val = body["warning_threshold_pct"]
        if not isinstance(val, (int, float)) or not (1 <= val <= 99):
            return json.dumps({"error": "warning_threshold_pct must be between 1 and 99"}), 400, JSON_HEADERS

    # Validate confirmed leak threshold
    if "confirmed_leak_threshold_sec" in body:
        val = body["confirmed_leak_threshold_sec"]
        if not isinstance(val, (int, float)) or val <= 0:
            return json.dumps({"error": "confirmed_leak_threshold_sec must be a positive number"}), 400, JSON_HEADERS

    updated = settings.update_settings(body)
    event_log.add_event(
        f"Settings updated: limit={updated['daily_limit_litres']} L, "
        f"warn at {updated['warning_threshold_pct']}%"
    )
    return json.dumps(updated), 200, JSON_HEADERS


# ===========================================================================
# ALARM RESET
# ===========================================================================

def handle_reset_alarm(request):
    """
    POST /api/reset-alarm
    Reset the system state from 'leak_alarm' or 'confirmed_leak' back to
    'normal'. Only allowed if all moisture sensor nodes are currently
    reading dry. This mirrors the hardware safety rule: you cannot clear
    an alarm while the triggering sensor is still wet.

    Also clears the confirmed-leak timer for the active mode, so if the
    sensor gets wet again later it starts a fresh countdown rather than
    immediately re-escalating using the old start time.
    """
    state = sensor_state.get_active_state()
    nodes = state["moisture_nodes"]

    # Check all connected nodes are dry
    wet_nodes = [
        name for name, n in nodes.items()
        if n.get("connected") and n.get("wet")
    ]

    if wet_nodes:
        msg = "Cannot reset, node(s) still wet: {}".format(", ".join(wet_nodes))
        return json.dumps({"error": msg}), 409, JSON_HEADERS

    # Clear the alarm state
    if sensor_state.get_mode() == "test":
        sensor_state.TEST_STATE["system_state"] = "normal"
    else:
        sensor_state.REAL_STATE["system_state"] = "normal"

    classification.reset_leak_timer()

    event_log.add_event("Leak alarm manually reset by user")
    return json.dumps({"status": "ok", "message": "Alarm reset"}), 200, JSON_HEADERS


# ===========================================================================
# MODE SWITCHING (real / test)
# ===========================================================================

def handle_get_mode(request):
    """
    GET /api/mode
    Return the current active mode.
    """
    return json.dumps({"mode": sensor_state.get_mode()}), 200, JSON_HEADERS


def handle_post_mode(request):
    """
    POST /api/mode
    Switch between real and test mode.
    Expects JSON body: {"mode": "real"} or {"mode": "test"}
    """
    try:
        body = json.loads(request.body)
        mode = body.get("mode")
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    if mode not in ("real", "test"):
        return json.dumps({"error": "mode must be 'real' or 'test'"}), 400, JSON_HEADERS

    previous = sensor_state.get_mode()
    sensor_state.set_mode(mode)

    # Only log when the mode actually changes
    if mode != previous:
        event_log.add_event(f"Switched to {mode} mode")

    return json.dumps({"mode": mode}), 200, JSON_HEADERS


# ===========================================================================
# TEST MODE , update individual values
# ===========================================================================

def handle_test_update(request):
    """
    POST /api/test/update
    Update one or more fields in the test state.
    Accepts a flat JSON body with any of these keys:
      - flow_rate_lpm        (number >= 0)
      - daily_total_litres   (number >= 0)
      - node_1_connected     (bool)
      - node_1_wet           (bool)
      - node_2_connected     (bool)
      - node_2_wet           (bool)
      - acoustic_connected   (bool)
      - acoustic_anomaly     (bool)
      - acoustic_signal_rms  (number >= 0)

    After updating, re-runs classification so the system state reflects
    the new test values immediately.
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    ts = sensor_state.TEST_STATE

    # --- Flow values ---
    if "flow_rate_lpm" in body:
        ts["flow_rate_lpm"] = max(0.0, float(body["flow_rate_lpm"]))

    if "daily_total_litres" in body:
        ts["daily_total_litres"] = max(0.0, float(body["daily_total_litres"]))

    # --- Moisture node 1 ---
    if "node_1_connected" in body:
        ts["moisture_nodes"]["node_1"]["connected"] = bool(body["node_1_connected"])
    if "node_1_wet" in body:
        ts["moisture_nodes"]["node_1"]["wet"] = bool(body["node_1_wet"])

    # --- Moisture node 2 ---
    if "node_2_connected" in body:
        ts["moisture_nodes"]["node_2"]["connected"] = bool(body["node_2_connected"])
    if "node_2_wet" in body:
        ts["moisture_nodes"]["node_2"]["wet"] = bool(body["node_2_wet"])

    # --- Acoustic sensor ---
    if "acoustic_connected" in body:
        ts["acoustic_sensor"]["connected"] = bool(body["acoustic_connected"])
    if "acoustic_anomaly" in body:
        ts["acoustic_sensor"]["anomaly"] = bool(body["acoustic_anomaly"])
    if "acoustic_signal_rms" in body:
        ts["acoustic_sensor"]["signal_rms"] = max(0.0, float(body["acoustic_signal_rms"]))

    # Re-run classification with the new test values
    new_state = classification.classify()

    return json.dumps({"status": "ok", "system_state": new_state}), 200, JSON_HEADERS


# ===========================================================================
# TEST MODE , preset scenarios
# ===========================================================================

# Each scenario is a dict of field names matching handle_test_update's
# accepted keys. New scenarios can be added here without touching any
# other file.
_SCENARIOS = {
    "normal": {
        "label": "Normal flow",
        "description": "Both nodes dry, low flow rate, well under daily limit.",
        "values": {
            "flow_rate_lpm": 3.5,
            "daily_total_litres": 20.0,
            "node_1_connected": True,  "node_1_wet": False,
            "node_2_connected": True,  "node_2_wet": False,
            "acoustic_connected": False, "acoustic_anomaly": False,
        }
    },
    "warning": {
        "label": "Approaching daily limit",
        "description": "Usage has crossed the warning threshold.",
        "values": {
            "flow_rate_lpm": 2.0,
            "daily_total_litres": 85.0,   # assumes 100 L limit and 80% threshold
            "node_1_connected": True,  "node_1_wet": False,
            "node_2_connected": True,  "node_2_wet": False,
            "acoustic_connected": False, "acoustic_anomaly": False,
        }
    },
    "leak_node1": {
        "label": "Leak at Node 1",
        "description": "Node 1 is reporting wet , leak alarm triggered.",
        "values": {
            "flow_rate_lpm": 0.0,
            "daily_total_litres": 30.0,
            "node_1_connected": True,  "node_1_wet": True,
            "node_2_connected": True,  "node_2_wet": False,
            "acoustic_connected": False, "acoustic_anomaly": False,
        }
    },
    "leak_node2": {
        "label": "Leak at Node 2",
        "description": "Node 2 is reporting wet , leak alarm triggered.",
        "values": {
            "flow_rate_lpm": 0.0,
            "daily_total_litres": 30.0,
            "node_1_connected": True,  "node_1_wet": False,
            "node_2_connected": True,  "node_2_wet": True,
            "acoustic_connected": False, "acoustic_anomaly": False,
        }
    },
    "abnormal": {
        "label": "Acoustic anomaly",
        "description": "Flow active and acoustic sensor detects an anomaly.",
        "values": {
            "flow_rate_lpm": 1.2,
            "daily_total_litres": 40.0,
            "node_1_connected": True,  "node_1_wet": False,
            "node_2_connected": True,  "node_2_wet": False,
            "acoustic_connected": True, "acoustic_anomaly": True,
            "acoustic_signal_rms": 0.85,
        }
    },
}


def handle_test_scenario(request):
    """
    POST /api/test/scenario
    Apply a named preset scenario to the test state.
    Expects JSON body: {"scenario": "<name>"}
    Valid scenario names: normal, warning, leak_node1, leak_node2, abnormal
    """
    try:
        body = json.loads(request.body)
        name = body.get("scenario", "")
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    if name not in _SCENARIOS:
        valid = list(_SCENARIOS.keys())
        return json.dumps({"error": f"Unknown scenario. Valid: {valid}"}), 400, JSON_HEADERS

    scenario = _SCENARIOS[name]

    # Re-use the update logic by building a fake request-like object
    class _FakeRequest:
        body = json.dumps(scenario["values"]).encode()

    result, status, headers = handle_test_update(_FakeRequest())
    event_log.add_event(f"Test scenario applied: {scenario['label']}")
    return result, status, headers


def get_scenarios_list():
    """
    Return a list of scenario metadata (name, label, description) for the
    dashboard to populate the scenario selector. Values are not included.
    """
    return [
        {"name": k, "label": v["label"], "description": v["description"]}
        for k, v in _SCENARIOS.items()
    ]


def handle_get_scenarios(request):
    """
    GET /api/test/scenarios
    Return the list of available preset scenarios.
    """
    return json.dumps(get_scenarios_list()), 200, JSON_HEADERS


def handle_test_reset(request):
    """
    POST /api/test/reset
    Reset all test state values back to defaults.
    """
    sensor_state.reset_test_state()
    event_log.add_event("Test state reset to defaults")
    return json.dumps({"status": "ok"}), 200, JSON_HEADERS


# ===========================================================================
# EVENT LOG
# ===========================================================================

def handle_get_events(request):
    """
    GET /api/events
    Return the 20 most recent events from the event log.
    """
    return json.dumps(event_log.get_recent_events(20)), 200, JSON_HEADERS


def handle_clear_events(request):
    """
    POST /api/events/clear
    Clear all events from the event log.
    """
    event_log.clear_log()
    return json.dumps({"status": "ok"}), 200, JSON_HEADERS


# ===========================================================================
# DAILY HISTORY
# ===========================================================================

def handle_get_history(request):
    """
    GET /api/history
    Return the archived daily usage totals, oldest first. Each entry is
    {"date": "YYYY-MM-DD", "total_litres": float}. Today's still-running
    total is not included, since it is not final yet; use /api/state for
    the live number.
    """
    return json.dumps(daily_history.get_history()), 200, JSON_HEADERS


# ===========================================================================
# ANALYTICS
# ===========================================================================

def handle_get_analytics(request):
    """
    GET /api/analytics
    Return the rolling 7-day average, the eco score, and the current
    under-limit streak, all computed from archived daily history.
    """
    return json.dumps(analytics.get_summary()), 200, JSON_HEADERS


# ===========================================================================
# TIME SYNC
# ===========================================================================

def handle_get_time_status(request):
    """
    GET /api/time/status
    Return whether the clock is synced, when it last synced, and whether
    that sync came from NTP (on the ESP32) or the system clock (on PC).
    """
    return json.dumps(ntp_sync.get_status()), 200, JSON_HEADERS


def handle_post_time_sync(request):
    """
    POST /api/time/sync
    Manually trigger a clock sync and return the resulting status.
    """
    ntp_sync.sync()
    return json.dumps(ntp_sync.get_status()), 200, JSON_HEADERS


# ===========================================================================
# THINGSPEAK CLOUD LOGGING
# ===========================================================================

def handle_get_cloud_status(request):
    """
    GET /api/cloud/status
    Return the current ThingSpeak configuration. The API key is included
    as-is; this project has no user accounts or auth layer, so there is
    nothing to hide it from that could not already read the config file
    directly off the device.
    """
    return json.dumps(thingspeak.get_config()), 200, JSON_HEADERS


def handle_post_cloud_settings(request):
    """
    POST /api/cloud/settings
    Update the ThingSpeak configuration. Expects a JSON body with any
    combination of: enabled (bool), api_key (string),
    update_interval_sec (number).
    """
    try:
        body = json.loads(request.body)
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    if "update_interval_sec" in body:
        val = body["update_interval_sec"]
        if not isinstance(val, (int, float)) or val <= 0:
            return json.dumps({"error": "update_interval_sec must be a positive number"}), 400, JSON_HEADERS

    updated = thingspeak.update_config(body)
    event_log.add_event("ThingSpeak cloud logging settings updated")
    return json.dumps(updated), 200, JSON_HEADERS


def handle_post_cloud_push(request):
    """
    POST /api/cloud/push
    Manually push the current active state to ThingSpeak right now,
    rather than waiting for the next scheduled push. Useful for testing
    a new API key from the dashboard before relying on the background task.
    """
    state = sensor_state.get_active_state()
    result = thingspeak.push_update(state)
    return json.dumps(result), 200, JSON_HEADERS


# ===========================================================================
# OTA UPDATES
# ===========================================================================

# Holds the most recently fetched manifest, so a two-step check-then-apply
# flow from the dashboard does not need to pass the whole manifest back
# and forth over the API.
_last_checked_manifest = {"manifest": None}


def handle_get_ota_status(request):
    """
    GET /api/ota/status
    Return the currently installed firmware version and whether a newer
    version was found the last time /api/ota/check was called.
    """
    manifest = _last_checked_manifest["manifest"]
    payload = {
        "current_version": ota.get_current_version(),
        "update_available": bool(manifest and ota.is_update_available(manifest)),
        "candidate_version": manifest.get("version") if manifest else None,
    }
    return json.dumps(payload), 200, JSON_HEADERS


def handle_post_ota_check(request):
    """
    POST /api/ota/check
    Fetch a manifest from the given URL and check whether it describes a
    newer version than what is currently installed. Expects JSON body:
    {"manifest_url": "https://..."}
    """
    try:
        body = json.loads(request.body)
        manifest_url = body.get("manifest_url")
    except Exception:
        return json.dumps({"error": "Invalid JSON"}), 400, JSON_HEADERS

    if not manifest_url:
        return json.dumps({"error": "manifest_url is required"}), 400, JSON_HEADERS

    manifest = ota.fetch_manifest(manifest_url)
    if manifest is None:
        return json.dumps({"error": "Could not fetch or parse manifest"}), 502, JSON_HEADERS

    _last_checked_manifest["manifest"] = manifest
    payload = {
        "current_version": ota.get_current_version(),
        "candidate_version": manifest.get("version"),
        "update_available": ota.is_update_available(manifest),
    }
    return json.dumps(payload), 200, JSON_HEADERS


def handle_post_ota_apply(request):
    """
    POST /api/ota/apply
    Download and write every file from the manifest most recently checked
    with /api/ota/check. Does not reboot automatically, since resetting
    the device in the middle of sending an HTTP response would cut the
    response off before the dashboard sees it. Call POST /api/ota/reboot
    once you have confirmed the response came back with applied: true.
    """
    manifest = _last_checked_manifest["manifest"]
    if manifest is None:
        return json.dumps({"error": "No manifest has been checked yet. Call /api/ota/check first."}), 400, JSON_HEADERS

    result = ota.apply_update(manifest)
    if result["applied"]:
        event_log.add_event("Firmware updated to version {}".format(manifest.get("version")))
        return json.dumps(result), 200, JSON_HEADERS
    return json.dumps(result), 502, JSON_HEADERS


def handle_post_ota_reboot(request):
    """
    POST /api/ota/reboot
    Restart the device to load newly applied firmware files. On PC this
    just logs what would happen, since a test server should not actually
    exit.
    """
    ota.reboot()
    return json.dumps({"status": "ok", "message": "Reboot requested"}), 200, JSON_HEADERS


# ===========================================================================
# ESP-NOW RECEIVER STATUS
# ===========================================================================

def handle_get_espnow_status(request):
    """
    GET /api/espnow/status
    Return whether the ESP-NOW receiver is available on this platform and,
    if so, whether it is currently active. available is always False on
    the PC test server, since there is no real radio to listen on there.
    """
    return json.dumps(espnow_receiver.get_status()), 200, JSON_HEADERS
