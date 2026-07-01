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
#   - Classification     (normal, warning, leak alarm, abnormal, confirmed leak)
#   - Alarm reset        (blocked when wet, allowed when dry)
#   - Settings           (save limit and threshold, validate bad input)
#   - Test state update  (dummy sensor values)
#   - Preset scenarios   (apply a named scenario and check the result)
#   - Daily history      (midnight rollover, archiving, capped storage)
#   - Analytics          (rolling average, eco score, streak)
#   - Time sync           (clock status on the PC no-op path)
#   - Cloud logging       (ThingSpeak config, disabled-by-default push)
#   - OTA updates         (manifest version comparison, apply validation)
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
import clock
import daily_history
import analytics
import ntp_sync
import thingspeak
import ota


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
    settings.reset_settings_to_defaults()

    # Clear the event log
    event_log.clear_log()

    # Reset the classifier's memory of the previous state and leak timers
    classification._previous_state["real"] = "normal"
    classification._previous_state["test"] = "normal"
    classification._leak_start_time["real"] = None
    classification._leak_start_time["test"] = None

    # Clear any test-controlled clock override left over from a previous
    # test, then reset daily history so it starts clean with today's date
    # and no archived entries.
    clock.clear_override()
    daily_history.reset_history()

    # Cloud logging should always start disabled and empty in tests, so no
    # test can accidentally end up making a real network call.
    thingspeak.update_config({"enabled": False, "api_key": "", "update_interval_sec": 60})


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


# =============================================================================
# TESTS — CONFIRMED LEAK ESCALATION
# Verify that a moisture node staying continuously wet escalates the
# system state from leak_alarm to confirmed_leak after the configured
# threshold, and that resetting the alarm clears the escalation timer.
#
# These tests use clock.set_override() / clock.advance_override() to
# simulate time passing instantly rather than sleeping for real minutes.
# =============================================================================

class TestConfirmedLeak:
    """Tests for the leak_alarm to confirmed_leak escalation."""

    def test_starts_as_leak_alarm(self, client):
        """
        The moment a node becomes wet, the state should be leak_alarm,
        not confirmed_leak, since no time has passed yet.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }

        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "A freshly wet node should be leak_alarm, not confirmed_leak"

    def test_does_not_escalate_before_threshold(self, client):
        """
        Just under the confirmed_leak_threshold_sec, the state should
        still be leak_alarm.

        Default threshold is 300 seconds.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()

        clock.advance_override(299)
        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "State should still be leak_alarm just under the threshold"

    def test_escalates_after_threshold(self, client):
        """
        Once the node has been wet for at least confirmed_leak_threshold_sec
        seconds, the state should escalate to confirmed_leak.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()

        clock.advance_override(300)
        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "confirmed_leak", \
            "State should escalate to confirmed_leak at the threshold"

    def test_custom_threshold_is_respected(self, client):
        """
        Changing confirmed_leak_threshold_sec through settings should
        change how long a leak takes to escalate.
        """
        post(client, "/api/settings", {"confirmed_leak_threshold_sec": 10})

        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()

        clock.advance_override(10)
        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "confirmed_leak", \
            "A 10 second threshold should escalate after 10 seconds"

    def test_drying_out_resets_the_timer(self, client):
        """
        If the node goes dry before the threshold, then gets wet again,
        the escalation timer should restart from zero rather than
        remembering the earlier wet period.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()

        clock.advance_override(250)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"]["wet"] = False
        classification.classify()

        clock.advance_override(100)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"]["wet"] = True
        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "Re-wetting after drying out should restart at leak_alarm, " \
            "not immediately count the earlier wet time"

    def test_reset_blocked_during_confirmed_leak(self, client):
        """
        The alarm reset endpoint should also block a confirmed_leak state
        while the node is still wet, the same as it blocks leak_alarm.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()
        clock.advance_override(300)
        classification.classify()

        res, body = post(client, "/api/reset-alarm", {})

        assert res.status_code == 409, \
            "Reset should be blocked during confirmed_leak while still wet"

    def test_reset_clears_escalation_timer(self, client):
        """
        After a successful reset, a brand new wet reading should start
        again at leak_alarm rather than immediately escalating using the
        previous leak's elapsed time.
        """
        clock.set_override(1000.0)
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {
            "connected": True, "wet": True
        }
        classification.classify()
        clock.advance_override(300)
        classification.classify()

        # Dry out and reset
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"]["wet"] = False
        post(client, "/api/reset-alarm", {})

        # Get wet again immediately
        sensor_state.REAL_STATE["moisture_nodes"]["node_1"]["wet"] = True
        classification.classify()
        _, state = get(client, "/api/state")

        assert state["system_state"] == "leak_alarm", \
            "A fresh leak after a reset should start at leak_alarm again"


# =============================================================================
# TESTS — DAILY HISTORY
# Verify that a day-boundary change archives yesterday's total and resets
# the running daily total, and that the /api/history endpoint reflects it.
# =============================================================================

class TestDailyHistory:
    """Tests for daily usage history and the midnight rollover."""

    def test_first_check_does_not_roll_over(self, client):
        """
        The very first time check_and_roll_over() runs after a reset,
        there is no previous day to compare against, so nothing should
        be archived yet.
        """
        clock.set_override(1750000000.0)
        daily_history.reset_history()

        rolled = daily_history.check_and_roll_over()

        assert rolled is False, "First check after a reset should not roll over"
        assert daily_history.get_history() == [], "No history should exist yet"

    def test_same_day_does_not_roll_over(self, client):
        """
        Calling check_and_roll_over() again on the same day should do
        nothing, since the date has not changed.
        """
        clock.set_override(1750000000.0)
        daily_history.reset_history()

        clock.advance_override(60)  # one minute later, same day
        rolled = daily_history.check_and_roll_over()

        assert rolled is False, "Same-day check should not roll over"

    def test_new_day_archives_and_resets(self, client):
        """
        When the date changes, the previous day's total should be
        archived and the running daily total should reset to zero.
        """
        clock.set_override(1750000000.0)
        daily_history.reset_history()
        sensor_state.REAL_STATE["daily_total_litres"] = 42.5

        clock.advance_override(24 * 60 * 60)
        rolled = daily_history.check_and_roll_over()

        assert rolled is True, "Crossing a day boundary should roll over"
        assert sensor_state.REAL_STATE["daily_total_litres"] == 0.0, \
            "Daily total should reset to zero after rollover"

        history = daily_history.get_history()
        assert len(history) == 1, "One day should be archived"
        assert history[0]["total_litres"] == 42.5, \
            "Archived total should match what was recorded before rollover"

    def test_history_endpoint_reflects_archive(self, client):
        """
        GET /api/history should return the same entries as
        daily_history.get_history().
        """
        clock.set_override(1750000000.0)
        daily_history.reset_history()
        sensor_state.REAL_STATE["daily_total_litres"] = 15.0
        clock.advance_override(24 * 60 * 60)
        daily_history.check_and_roll_over()

        res, body = get(client, "/api/history")

        assert res.status_code == 200
        assert len(body) == 1
        assert body[0]["total_litres"] == 15.0

    def test_history_capped_at_max_days(self, client):
        """
        History should never grow past MAX_HISTORY_DAYS entries; the
        oldest entries should be dropped first.
        """
        clock.set_override(1750000000.0)
        daily_history.reset_history()

        for _ in range(daily_history.MAX_HISTORY_DAYS + 5):
            sensor_state.REAL_STATE["daily_total_litres"] = 10.0
            clock.advance_override(24 * 60 * 60)
            daily_history.check_and_roll_over()

        history = daily_history.get_history()
        assert len(history) == daily_history.MAX_HISTORY_DAYS, \
            "History should be capped at MAX_HISTORY_DAYS entries"


# =============================================================================
# TESTS — ANALYTICS
# Verify the rolling average, eco score, and streak calculations against
# a manually constructed history.
# =============================================================================

class TestAnalytics:
    """Tests for the rolling average, eco score, and streak features."""

    def _set_history(self, entries):
        """Directly install a history list for a test, bypassing rollover."""
        daily_history._state["entries"] = entries
        daily_history._save(daily_history._state)

    def test_rolling_average_with_no_history(self, client):
        """
        With no archived history, the rolling average should be 0.0
        rather than dividing by zero.
        """
        assert analytics.rolling_average(7) == 0.0

    def test_rolling_average_matches_manual_calculation(self, client):
        """
        The rolling average over the last N days should match a plain
        average of those days' totals.
        """
        self._set_history([
            {"date": "2026-06-24", "total_litres": 80.0},
            {"date": "2026-06-25", "total_litres": 90.0},
            {"date": "2026-06-26", "total_litres": 150.0},
            {"date": "2026-06-27", "total_litres": 60.0},
            {"date": "2026-06-28", "total_litres": 70.0},
        ])

        expected = round((80.0 + 90.0 + 150.0 + 60.0 + 70.0) / 5, 1)
        assert analytics.rolling_average(5) == expected

    def test_eco_score_is_clamped_between_0_and_100(self, client):
        """
        Even with usage far above or far below the daily limit, the eco
        score should stay within the 0 to 100 range.
        """
        self._set_history([{"date": "2026-06-28", "total_litres": 1000.0}])
        assert 0 <= analytics.eco_score(1) <= 100

        self._set_history([{"date": "2026-06-28", "total_litres": 0.0}])
        assert analytics.eco_score(1) == 100, \
            "Zero usage should produce a perfect eco score"

    def test_streak_counts_consecutive_under_limit_days(self, client):
        """
        The streak should count consecutive recent days at or under the
        daily limit, stopping at the first day that went over.
        """
        # Default daily limit is 100.0 L
        self._set_history([
            {"date": "2026-06-24", "total_litres": 150.0},  # over limit
            {"date": "2026-06-25", "total_litres": 90.0},   # under
            {"date": "2026-06-26", "total_litres": 95.0},   # under
        ])

        assert analytics.current_streak() == 2, \
            "Streak should count the two most recent under-limit days"

    def test_streak_is_zero_after_an_over_limit_day(self, client):
        """
        If the most recent completed day was over the limit, the streak
        should be zero.
        """
        self._set_history([
            {"date": "2026-06-27", "total_litres": 50.0},
            {"date": "2026-06-28", "total_litres": 150.0},  # over limit
        ])

        assert analytics.current_streak() == 0

    def test_analytics_endpoint_returns_all_fields(self, client):
        """
        GET /api/analytics should return all three computed figures
        together.
        """
        self._set_history([{"date": "2026-06-28", "total_litres": 50.0}])

        res, body = get(client, "/api/analytics")

        assert res.status_code == 200
        assert "rolling_average_litres" in body
        assert "eco_score" in body
        assert "streak_days" in body


# =============================================================================
# TESTS — TIME SYNC
# On the PC test server there is no ntptime module, so sync() takes the
# no-op path and should always report success.
# =============================================================================

class TestTimeSync:
    """Tests for the clock sync status endpoints."""

    def test_sync_succeeds_on_pc(self, client):
        """
        sync() should return True on PC, since it treats the system
        clock as already correct.
        """
        assert ntp_sync.sync() is True

    def test_status_reports_system_clock_source_on_pc(self, client):
        """
        On PC (no ntptime module available), the status source should
        be "system_clock", not "ntp".
        """
        ntp_sync.sync()
        status = ntp_sync.get_status()

        assert status["synced"] is True
        assert status["source"] == "system_clock"

    def test_time_status_endpoint(self, client):
        """GET /api/time/status should return the current sync status."""
        res, body = get(client, "/api/time/status")

        assert res.status_code == 200
        assert "synced" in body

    def test_time_sync_endpoint_triggers_a_sync(self, client):
        """POST /api/time/sync should trigger a sync and return status."""
        res, body = post(client, "/api/time/sync", {})

        assert res.status_code == 200
        assert body["synced"] is True


# =============================================================================
# TESTS — CLOUD LOGGING (THINGSPEAK)
# Cloud logging must stay off unless explicitly enabled with an API key,
# and must never attempt a real network call during these tests.
# =============================================================================

class TestCloudLogging:
    """Tests for the ThingSpeak configuration and push logic."""

    def test_disabled_by_default(self, client):
        """Cloud logging should start disabled after a reset."""
        res, body = get(client, "/api/cloud/status")

        assert res.status_code == 200
        assert body["enabled"] is False

    def test_push_skipped_when_disabled(self, client):
        """
        push_update() should not attempt a network call, and should
        report why, when cloud logging is disabled.
        """
        result = thingspeak.push_update(sensor_state.REAL_STATE)

        assert result["sent"] is False
        assert "disabled" in result["reason"]

    def test_push_skipped_with_no_api_key(self, client):
        """
        Enabling cloud logging without providing an API key should still
        skip the push rather than attempting a request with a blank key.
        """
        thingspeak.update_config({"enabled": True, "api_key": ""})

        result = thingspeak.push_update(sensor_state.REAL_STATE)

        assert result["sent"] is False
        assert "api key" in result["reason"]

    def test_cloud_settings_endpoint_updates_config(self, client):
        """POST /api/cloud/settings should update and persist the config."""
        res, body = post(client, "/api/cloud/settings", {
            "enabled": True,
            "api_key": "TESTKEY123",
            "update_interval_sec": 30,
        })

        assert res.status_code == 200
        assert body["enabled"] is True
        assert body["api_key"] == "TESTKEY123"
        assert body["update_interval_sec"] == 30

    def test_negative_interval_rejected(self, client):
        """A zero or negative update interval should be rejected."""
        res, body = post(client, "/api/cloud/settings", {
            "update_interval_sec": -5,
        })

        assert res.status_code == 400
        assert "error" in body

    def test_manual_push_endpoint_does_not_crash_when_disabled(self, client):
        """
        POST /api/cloud/push should return a normal response describing
        why nothing was sent, rather than erroring, when disabled.
        """
        res, body = post(client, "/api/cloud/push", {})

        assert res.status_code == 200
        assert body["sent"] is False


# =============================================================================
# TESTS — OTA UPDATES
# These tests exercise manifest comparison and file-writing logic without
# making a real network request, by passing manifest dictionaries directly.
# =============================================================================

class TestOTA:
    """Tests for OTA version comparison and update application."""

    def test_newer_version_is_available(self, client):
        """A manifest with a higher version number should be detected."""
        manifest = {"version": "9.9.9", "files": {}}
        assert ota.is_update_available(manifest) is True

    def test_older_version_is_not_available(self, client):
        """A manifest with a lower version number should be rejected."""
        manifest = {"version": "0.0.1", "files": {}}
        assert ota.is_update_available(manifest) is False

    def test_apply_update_rejects_empty_file_list(self, client):
        """
        A manifest with no files listed should not be treated as a valid
        update to apply.
        """
        result = ota.apply_update({"version": "1.0.0", "files": {}})

        assert result["applied"] is False
        assert "no files" in result["reason"]

    def test_ota_status_endpoint_reports_current_version(self, client):
        """GET /api/ota/status should always report a current_version."""
        res, body = get(client, "/api/ota/status")

        assert res.status_code == 200
        assert "current_version" in body
        assert body["update_available"] is False, \
            "No update should be flagged before /api/ota/check has run"

    def test_ota_check_requires_manifest_url(self, client):
        """POST /api/ota/check without a manifest_url should return 400."""
        res, body = post(client, "/api/ota/check", {})

        assert res.status_code == 400
        assert "error" in body

    def test_ota_apply_requires_a_prior_check(self, client):
        """
        POST /api/ota/apply before any manifest has been checked should
        return 400 rather than attempting to apply nothing.
        """
        res, body = post(client, "/api/ota/apply", {})

        assert res.status_code == 400
        assert "error" in body
