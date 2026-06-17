# =============================================================================
# test_api.py
# API tests for the Water Monitor system.

#       pytest test_api.py -v
#
#       pytest test_api.py -v -k "test_switch_to_test_mode"
#
# HOW THESE TESTS WORK
# --------------------
# Each test function:
#   1. Uses a Flask "test client" to send a fake HTTP request to the server
#   2. Checks that the response status code and body are what we expect
#   3. Passes if everything matches, fails if anything is wrong
#
# The test client talks directly to the Flask app in memory, no browser,
# no real network connection, no server process needed.
#
# WHAT IS BEING TESTED
# --------------------
# The critical API endpoints:
#   - Mode switching     (real <-> test)
#   - Classification     (normal, warning, leak alarm, abnormal)
#   - Alarm reset        (blocked when wet, allowed when dry)
#   - Settings           (save limit and threshold, validate bad input)
#   - Test state update  (dummy sensor values)
#   - Preset scenarios   (apply a named scenario and check the result)
# =============================================================================

import json
import pytest

# We import the Flask app from server_pc so the test client can use it.
# All routes defined in server_pc.py are available to the test client.
from server_pc import app

# Import the state modules so we can reset them between tests.
# This ensures each test starts with a clean slate.
import sensor_state
import settings
import event_log
import classification


# =============================================================================
# FIXTURES
# A fixture is a function that runs before each test to set up a known
# starting state. pytest automatically injects fixtures into test functions
# that list them as parameters.
# =============================================================================

@pytest.fixture
def client():
    """
    Create a Flask test client for sending fake HTTP requests.

    The test client works exactly like a real browser sending requests,
    except everything happens in memory with no network involved.

    This fixture also resets all system state before each test so that
    tests do not interfere with each other.
    """
    # Put Flask into testing mode — this gives better error messages
    app.config["TESTING"] = True

    # Reset all state to defaults before every test
    _reset_all_state()

    # Yield the test client to the test function
    with app.test_client() as client:
        yield client


def _reset_all_state():
    """
    Reset all system state to defaults.
    Called before every test to ensure a clean starting point.
    """
    # Reset both real and test sensor states
    sensor_state.REAL_STATE["flow_rate_lpm"]      = 0.0
    sensor_state.REAL_STATE["daily_total_litres"] = 0.0
    sensor_state.REAL_STATE["system_state"]       = "normal"
    sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {"connected": False, "wet": False}
    sensor_state.REAL_STATE["moisture_nodes"]["node_2"] = {"connected": False, "wet": False}
    sensor_state.REAL_STATE["acoustic_sensor"]    = {"connected": False, "signal_rms": 0.0, "anomaly": False}

    sensor_state.reset_test_state()

    # Reset mode to real
    sensor_state.set_mode("real")

    # Reset settings to defaults
    settings.update_settings({
        "daily_limit_litres":   100.0,
        "warning_threshold_pct": 80.0,
    })

    # Clear the event log
    event_log.clear_log()

    # Reset the classifier's memory of the previous state
    classification._previous_state["real"] = "normal"
    classification._previous_state["test"] = "normal"


# =============================================================================
# HELPER FUNCTIONS
# Small utilities to reduce repetition in the tests below.
# =============================================================================

def post(client, url, data):
    """
    Send a POST request with a JSON body and return the parsed response.

    Args:
        client: Flask test client
        url:    API endpoint path (e.g. "/api/mode")
        data:   Python dictionary to send as the JSON body

    Returns:
        tuple: (response_object, parsed_json_body)
    """
    response = client.post(
        url,
        data=json.dumps(data),
        content_type="application/json"
    )
    return response, json.loads(response.data)


def get(client, url):
    """
    Send a GET request and return the parsed response.

    Args:
        client: Flask test client
        url:    API endpoint path (e.g. "/api/state")

    Returns:
        tuple: (response_object, parsed_json_body)
    """
    response = client.get(url)
    return response, json.loads(response.data)


# =============================================================================
# TESTS — MODE SWITCHING
# Verify that switching between real and test mode works correctly and
# that the mode is reflected in the /api/state response.
# =============================================================================

class TestModeSwitching:
    """Tests for switching between real sensor data and test mode."""

    def test_default_mode_is_real(self, client):
        """
        The system should start in real mode.
        Check that /api/state reports mode = "real" on a fresh start.
        """
        res, body = get(client, "/api/state")

        assert res.status_code == 200, "Expected 200 OK"
        assert body["mode"] == "real", "System should start in real mode"

    def test_switch_to_test_mode(self, client):
        """
        Switching to test mode should succeed and return mode = "test".
        """
        res, body = post(client, "/api/mode", {"mode": "test"})

        assert res.status_code == 200, "Expected 200 OK"
        assert body["mode"] == "test", "Mode should now be test"

    def test_switch_back_to_real_mode(self, client):
        """
        After switching to test mode, switching back to real should work.
        """
        # First go to test mode
        post(client, "/api/mode", {"mode": "test"})

        # Then switch back to real
        res, body = post(client, "/api/mode", {"mode": "real"})

        assert res.status_code == 200
        assert body["mode"] == "real", "Mode should be back to real"

    def test_invalid_mode_rejected(self, client):
        """
        Sending an invalid mode string should return a 400 Bad Request error.
        The mode should stay unchanged.
        """
        res, body = post(client, "/api/mode", {"mode": "invalid_mode"})

        assert res.status_code == 400, "Invalid mode should return 400"
        assert "error" in body, "Response should contain an error message"

    def test_state_reflects_active_mode(self, client):
        """
        After switching to test mode, /api/state should read from
        the test state, not the real state.

        We set a flow rate in the test state and verify /api/state
        returns the test value, not the real value (which stays at 0).
        """
        # Switch to test mode
        post(client, "/api/mode", {"mode": "test"})

        # Set a flow rate only in the test state
        post(client, "/api/test/update", {"flow_rate_lpm": 5.5})

        # Check that /api/state returns the test value
        res, body = get(client, "/api/state")

        assert body["flow_rate_lpm"] == 5.5, \
            "State should reflect test mode flow rate"
        assert sensor_state.REAL_STATE["flow_rate_lpm"] == 0.0, \
            "Real state should be unchanged"


# =============================================================================
# TESTS — CLASSIFICATION
# Verify that the classifier correctly determines the system state based
# on the active sensor readings and settings.
# =============================================================================

class TestClassification:
    """Tests for the system state classification algorithm."""

    def test_normal_state_by_default(self, client):
        """
        With no sensors triggered and usage well under the limit,
        the system state should be normal.
        """
        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "normal"

    def test_warning_when_usage_crosses_threshold(self, client):
        """
        When daily usage crosses the warning threshold percentage,
        the system state should become 'warning'.

        Setup: limit = 100 L, threshold = 80%, usage = 85 L
        Expected: warning state
        """
        # Set usage above the 80% warning threshold
        sensor_state.REAL_STATE["daily_total_litres"] = 85.0

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "warning", \
            "Usage at 85% of limit should trigger warning"

    def test_no_warning_below_threshold(self, client):
        """
        Usage below the warning threshold should not trigger a warning.

        Setup: limit = 100 L, threshold = 80%, usage = 75 L
        Expected: normal state
        """
        sensor_state.REAL_STATE["daily_total_litres"] = 75.0

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "normal", \
            "Usage at 75% should not trigger warning"

    def test_leak_alarm_when_node_wet(self, client):
        """
        When any moisture sensor node reports wet, the system should
        immediately enter leak_alarm state regardless of other sensors.

        Setup: Node 1 connected and wet
        Expected: leak_alarm state
        """
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True,
            "wet": True
        }

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "leak_alarm", \
            "Wet moisture sensor should trigger leak alarm"

    def test_leak_alarm_takes_priority_over_warning(self, client):
        """
        Leak alarm has the highest priority. Even if usage is also above
        the warning threshold, leak_alarm should be the reported state.

        Setup: usage = 90 L (above warning), node 1 wet
        Expected: leak_alarm (not warning)
        """
        sensor_state.REAL_STATE["daily_total_litres"] = 90.0
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True,
            "wet": True
        }

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "leak_alarm", \
            "Leak alarm should take priority over warning state"

    def test_abnormal_when_flow_and_acoustic_anomaly(self, client):
        """
        When flow is non-zero AND the acoustic sensor detects an anomaly,
        the state should be 'abnormal'.

        Setup: flow = 1.5 L/min, acoustic connected and anomaly = True
        Expected: abnormal state
        """
        sensor_state.REAL_STATE["flow_rate_lpm"] = 1.5
        sensor_state.REAL_STATE["acoustic_sensor"] = {
            "connected": True,
            "signal_rms": 0.9,
            "anomaly": True
        }

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "abnormal", \
            "Flow + acoustic anomaly should trigger abnormal state"

    def test_no_abnormal_without_acoustic_sensor(self, client):
        """
        If the acoustic sensor is not connected, flow alone should not
        trigger an abnormal state.

        Setup: flow = 1.5 L/min, acoustic sensor NOT connected
        Expected: normal state
        """
        sensor_state.REAL_STATE["flow_rate_lpm"] = 1.5
        sensor_state.REAL_STATE["acoustic_sensor"] = {
            "connected": False,
            "signal_rms": 0.0,
            "anomaly": False
        }

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "normal", \
            "Flow without acoustic sensor should not trigger abnormal"

    def test_classification_uses_test_state_in_test_mode(self, client):
        """
        When in test mode, the classifier should read from the test state,
        not the real state.

        Setup: real state has a wet node (would trigger leak alarm),
               test state has no wet nodes (should be normal)
        Expected: normal state (because we are in test mode)
        """
        # Set real state to have a wet node
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }

        # Switch to test mode (test state has no wet nodes)
        post(client, "/api/mode", {"mode": "test"})

        classification.classify()
        res, body = get(client, "/api/state")

        assert body["system_state"] == "normal", \
            "Classifier should use test state, not real state, in test mode"


# =============================================================================
# TESTS — ALARM RESET
# Verify the alarm reset rules:
#   - Cannot reset while any node is still wet
#   - Can reset when all nodes are dry
# =============================================================================

class TestAlarmReset:
    """Tests for the leak alarm reset endpoint."""

    def test_reset_blocked_when_node_wet(self, client):
        """
        Resetting the alarm should be blocked if any connected moisture
        sensor is still reporting wet.

        Expected: 409 Conflict response with an error message.
        """
        # Set node 1 as connected and wet
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True,
            "wet": True
        }
        sensor_state.REAL_STATE["system_state"] = "leak_alarm"

        res, body = post(client, "/api/reset-alarm", {})

        assert res.status_code == 409, \
            "Reset should be blocked (409 Conflict) while node is wet"
        assert "error" in body, "Response should contain an error message"
        assert "still wet" in body["error"].lower(), \
            "Error message should mention the wet node"

    def test_reset_allowed_when_all_nodes_dry(self, client):
        """
        Resetting the alarm should succeed when all connected nodes
        are reporting dry.

        Expected: 200 OK and system state returns to normal.
        """
        # Node 1 connected but dry (alarm was cleared physically)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True,
            "wet": False
        }
        sensor_state.REAL_STATE["system_state"] = "leak_alarm"

        res, body = post(client, "/api/reset-alarm", {})

        assert res.status_code == 200, "Reset should succeed when nodes are dry"
        assert body["status"] == "ok"

        # Verify the system state was actually cleared
        _, state = get(client, "/api/state")
        assert state["system_state"] == "normal", \
            "System state should be normal after successful reset"

    def test_reset_allowed_when_no_nodes_connected(self, client):
        """
        If no nodes are connected at all, there are no wet nodes to block
        the reset, so it should be allowed.
        """
        # Both nodes disconnected
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": False, "wet": False
        }
        sensor_state.REAL_STATE["moisture_nodes"]["node_2"] = {
            "connected": False, "wet": False
        }
        sensor_state.REAL_STATE["system_state"] = "leak_alarm"

        res, body = post(client, "/api/reset-alarm", {})

        assert res.status_code == 200, \
            "Reset should be allowed when no nodes are connected"

    def test_reset_logs_event(self, client):
        """
        A successful alarm reset should add an entry to the event log.
        """
        sensor_state.REAL_STATE["system_state"] = "leak_alarm"

        post(client, "/api/reset-alarm", {})

        _, events = get(client, "/api/events")
        messages = [e["message"] for e in events]

        assert any("reset" in m.lower() for m in messages), \
            "A reset event should appear in the event log"


# =============================================================================
# TESTS — SETTINGS
# Verify that settings can be saved and that invalid values are rejected.
# =============================================================================

class TestSettings:
    """Tests for reading and updating user settings."""

    def test_default_settings(self, client):
        """
        The default daily limit should be 100 L and the default warning
        threshold should be 80%.
        """
        res, body = get(client, "/api/settings")

        assert res.status_code == 200
        assert body["daily_limit_litres"]   == 100.0
        assert body["warning_threshold_pct"] == 80.0

    def test_save_valid_settings(self, client):
        """
        Saving a valid daily limit and warning threshold should succeed
        and the new values should be reflected immediately.
        """
        res, body = post(client, "/api/settings", {
            "daily_limit_litres":    150.0,
            "warning_threshold_pct": 70.0,
        })

        assert res.status_code == 200
        assert body["daily_limit_litres"]    == 150.0
        assert body["warning_threshold_pct"] == 70.0

        # Confirm the values are now returned by GET as well
        _, fetched = get(client, "/api/settings")
        assert fetched["daily_limit_litres"]    == 150.0
        assert fetched["warning_threshold_pct"] == 70.0

    def test_negative_limit_rejected(self, client):
        """
        A negative or zero daily limit should be rejected with a 400 error.
        """
        res, body = post(client, "/api/settings", {
            "daily_limit_litres": -10.0
        })

        assert res.status_code == 400, "Negative limit should be rejected"
        assert "error" in body

    def test_zero_limit_rejected(self, client):
        """
        A zero daily limit should be rejected.
        """
        res, body = post(client, "/api/settings", {
            "daily_limit_litres": 0
        })

        assert res.status_code == 400, "Zero limit should be rejected"

    def test_threshold_above_99_rejected(self, client):
        """
        A warning threshold above 99% should be rejected.
        A threshold of 100% would mean the warning only fires when the
        limit is fully reached, which is the same as no warning.
        """
        res, body = post(client, "/api/settings", {
            "warning_threshold_pct": 100.0
        })

        assert res.status_code == 400, "Threshold >= 100 should be rejected"

    def test_threshold_below_1_rejected(self, client):
        """
        A warning threshold below 1% should be rejected.
        """
        res, body = post(client, "/api/settings", {
            "warning_threshold_pct": 0
        })

        assert res.status_code == 400, "Threshold of 0 should be rejected"

    def test_partial_update_works(self, client):
        """
        Sending only one setting key should update that key without
        changing the other settings.
        """
        # Only update the limit, leave the threshold unchanged
        post(client, "/api/settings", {"daily_limit_litres": 200.0})

        _, body = get(client, "/api/settings")

        assert body["daily_limit_litres"]    == 200.0, "Limit should be updated"
        assert body["warning_threshold_pct"] == 80.0,  "Threshold should be unchanged"

    def test_settings_affect_usage_percentage(self, client):
        """
        After changing the daily limit, the usage percentage reported
        by /api/state should recalculate based on the new limit.

        Setup: usage = 50 L
               old limit = 100 L  -> 50%
               new limit = 200 L  -> 25%
        """
        sensor_state.REAL_STATE["daily_total_litres"] = 50.0

        # With the default 100 L limit, usage should be 50%
        _, state = get(client, "/api/state")
        assert state["usage_pct"] == 50.0, "Usage should be 50% with 100 L limit"

        # Change the limit to 200 L
        post(client, "/api/settings", {"daily_limit_litres": 200.0})

        # Now usage should be 25%
        _, state = get(client, "/api/state")
        assert state["usage_pct"] == 25.0, "Usage should be 25% with 200 L limit"


# =============================================================================
# TESTS — TEST MODE STATE UPDATE
# Verify that the test mode dummy value injection works correctly and
# that it never touches the real sensor state.
# =============================================================================

class TestModeStateUpdate:
    """Tests for injecting dummy sensor values in test mode."""

    def test_update_flow_rate_in_test_mode(self, client):
        """
        Setting a flow rate in test mode should be visible in /api/state
        when in test mode, and should not affect the real state.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/update", {"flow_rate_lpm": 7.3})

        _, state = get(client, "/api/state")

        assert state["flow_rate_lpm"] == 7.3, \
            "Test state flow rate should be 7.3"
        assert sensor_state.REAL_STATE["flow_rate_lpm"] == 0.0, \
            "Real state should be unaffected"

    def test_update_moisture_node_in_test_mode(self, client):
        """
        Setting a moisture node to wet in test mode should trigger
        the leak alarm classification.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/update", {
            "node_1_connected": True,
            "node_1_wet":       True,
        })

        # The update endpoint re-runs classification automatically
        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "Wet node in test mode should trigger leak alarm"
        assert state["moisture_nodes"]["node_1"]["wet"] is True

    def test_reset_test_state_restores_defaults(self, client):
        """
        After applying test values, resetting the test state should
        return all values to zero/false/disconnected defaults.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/update", {
            "flow_rate_lpm":    9.0,
            "daily_total_litres": 50.0,
            "node_1_connected": True,
            "node_1_wet":       True,
        })

        # Reset test state
        res, body = post(client, "/api/test/reset", {})
        assert res.status_code == 200

        _, state = get(client, "/api/state")

        assert state["flow_rate_lpm"]      == 0.0,   "Flow should reset to 0"
        assert state["daily_total_litres"] == 0.0,   "Daily total should reset to 0"
        assert state["moisture_nodes"]["node_1"]["wet"] is False, \
            "Node 1 should reset to dry"


# =============================================================================
# TESTS — PRESET SCENARIOS
# Verify that each named scenario applies the correct dummy values and
# produces the expected system state.
# =============================================================================

class TestPresetScenarios:
    """Tests for the preset test scenario system."""

    def test_scenarios_list_not_empty(self, client):
        """
        The /api/test/scenarios endpoint should return at least one scenario.
        """
        res, body = get(client, "/api/test/scenarios")

        assert res.status_code == 200
        assert len(body) > 0, "There should be at least one scenario"
        assert "name" in body[0],  "Each scenario should have a name"
        assert "label" in body[0], "Each scenario should have a label"

    def test_normal_scenario_produces_normal_state(self, client):
        """
        Applying the 'normal' scenario should result in normal system state.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/scenario", {"scenario": "normal"})

        _, state = get(client, "/api/state")

        assert state["system_state"] == "normal", \
            "Normal scenario should produce normal state"

    def test_leak_node1_scenario_produces_alarm(self, client):
        """
        Applying the 'leak_node1' scenario should result in leak_alarm state
        with node 1 reported as wet.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/scenario", {"scenario": "leak_node1"})

        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "Leak node 1 scenario should trigger leak alarm"
        assert state["moisture_nodes"]["node_1"]["wet"] is True, \
            "Node 1 should be wet in this scenario"

    def test_warning_scenario_produces_warning_state(self, client):
        """
        Applying the 'warning' scenario should result in warning state
        because the dummy daily total is above the warning threshold.
        """
        post(client, "/api/mode", {"mode": "test"})
        post(client, "/api/test/scenario", {"scenario": "warning"})

        _, state = get(client, "/api/state")

        assert state["system_state"] == "warning", \
            "Warning scenario should produce warning state"

    def test_invalid_scenario_rejected(self, client):
        """
        Requesting a scenario name that does not exist should return
        a 400 Bad Request error.
        """
        post(client, "/api/mode", {"mode": "test"})
        res, body = post(client, "/api/test/scenario", {"scenario": "does_not_exist"})

        assert res.status_code == 400, "Unknown scenario should return 400"
        assert "error" in body
