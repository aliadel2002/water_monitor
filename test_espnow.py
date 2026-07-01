# =============================================================================
# test_espnow.py
# Tests for espnow_receiver.py.
#
# The espnow module only exists on real ESP32 hardware, so none of the
# actual radio calls (init(), receiver_loop() looping forever, irecv())
# can be exercised here. What can be tested on PC is everything in
# _handle_packet(): JSON decoding, field validation, node ID checking,
# the state_changed detection that avoids flooding the event log, and
# the resulting write into sensor_state.REAL_STATE. That is also where
# almost all of the actual bugs in this kind of code tend to live, the
# radio layer itself is either working or not, but decoding logic is
# where a malformed or unexpected packet can do real damage.
#
#       pytest test_espnow.py -v
# =============================================================================

import json
import pytest

import espnow_receiver
import sensor_state
import event_log


FAKE_MAC = b"\xaa\xbb\xcc\xdd\xee\xff"


@pytest.fixture
def clean_state():
    """Reset the moisture nodes and event log before each test."""
    sensor_state.REAL_STATE["moisture_nodes"]["node_1"] = {"connected": False, "wet": False}
    sensor_state.REAL_STATE["moisture_nodes"]["node_2"] = {"connected": False, "wet": False}
    event_log.clear_log()
    yield


def _send(node_id, wet):
    """Build a packet payload the same way node_firmware.py does, and
    hand it to _handle_packet() as if it had just arrived over the radio."""
    payload = json.dumps({"node_id": node_id, "wet": wet}).encode("utf-8")
    espnow_receiver._handle_packet(FAKE_MAC, payload)


class TestPacketHandling:
    """Tests for decoding and applying a single incoming packet."""

    def test_valid_wet_packet_updates_state(self, clean_state):
        """A well-formed wet packet should mark the node connected and wet."""
        _send("node_1", True)

        node = sensor_state.REAL_STATE["moisture_nodes"]["node_1"]
        assert node["connected"] is True
        assert node["wet"] is True

    def test_valid_dry_packet_updates_state(self, clean_state):
        """A well-formed dry packet should mark the node connected and dry."""
        _send("node_2", False)

        node = sensor_state.REAL_STATE["moisture_nodes"]["node_2"]
        assert node["connected"] is True
        assert node["wet"] is False

    def test_first_packet_from_a_node_logs_an_event(self, clean_state):
        """
        The very first packet from a node should log an event, since going
        from disconnected to connected counts as a meaningful change even
        if the reading itself is dry.
        """
        _send("node_1", False)

        events = event_log.get_recent_events(10)
        assert len(events) == 1
        assert "node_1" in events[0]["message"]

    def test_repeated_identical_reading_does_not_log_again(self, clean_state):
        """
        Once a node is connected and dry, further dry packets should not
        add more events, only an actual change in wet/dry should log.
        This is what keeps a 5 second heartbeat from flooding the log.
        """
        _send("node_1", False)
        _send("node_1", False)
        _send("node_1", False)

        events = event_log.get_recent_events(10)
        assert len(events) == 1, "Only the first packet should have logged an event"

    def test_change_from_dry_to_wet_logs_a_new_event(self, clean_state):
        """A transition from dry to wet should log a second event."""
        _send("node_1", False)
        _send("node_1", True)

        events = event_log.get_recent_events(10)
        assert len(events) == 2
        assert "WET" in events[-1]["message"]

    def test_malformed_json_is_discarded(self, clean_state):
        """
        A packet that is not valid JSON should be silently discarded
        rather than crashing the receiver loop.
        """
        espnow_receiver._handle_packet(FAKE_MAC, b"not valid json{{{")

        node = sensor_state.REAL_STATE["moisture_nodes"]["node_1"]
        assert node["connected"] is False, "State should be untouched by a bad packet"
        assert event_log.get_recent_events(10) == []

    def test_packet_missing_wet_field_is_discarded(self, clean_state):
        """A packet with node_id but no wet field should be discarded."""
        payload = json.dumps({"node_id": "node_1"}).encode("utf-8")
        espnow_receiver._handle_packet(FAKE_MAC, payload)

        node = sensor_state.REAL_STATE["moisture_nodes"]["node_1"]
        assert node["connected"] is False

    def test_packet_missing_node_id_field_is_discarded(self, clean_state):
        """A packet with wet but no node_id field should be discarded."""
        payload = json.dumps({"wet": True}).encode("utf-8")
        espnow_receiver._handle_packet(FAKE_MAC, payload)

        for node in sensor_state.REAL_STATE["moisture_nodes"].values():
            assert node["connected"] is False

    def test_unknown_node_id_is_discarded(self, clean_state):
        """
        A packet from a node_id that is not in KNOWN_NODE_IDS should be
        discarded rather than silently creating a new, unexpected entry
        in moisture_nodes.
        """
        _send("node_99", True)

        assert "node_99" not in sensor_state.REAL_STATE["moisture_nodes"]
        for node in sensor_state.REAL_STATE["moisture_nodes"].values():
            assert node["connected"] is False

    def test_non_boolean_wet_value_is_coerced(self, clean_state):
        """
        node_firmware.py always sends a real boolean, but the receiver
        should not crash if a future firmware version sends a truthy or
        falsy value of another type instead (for example 1 or 0).
        """
        payload = json.dumps({"node_id": "node_1", "wet": 1}).encode("utf-8")
        espnow_receiver._handle_packet(FAKE_MAC, payload)

        assert sensor_state.REAL_STATE["moisture_nodes"]["node_1"]["wet"] is True


class TestStatusAndPlatformGuards:
    """
    Tests for get_status() and the platform guards that let this module
    be imported at all on a machine with no espnow hardware.
    """

    def test_available_is_false_on_pc(self):
        """
        There is no espnow module in this test environment, so
        get_status() should always report available: False here.
        """
        status = espnow_receiver.get_status()
        assert status["available"] is False
        assert status["active"] is False

    def test_known_nodes_reported(self):
        """get_status() should list the known node IDs regardless of platform."""
        status = espnow_receiver.get_status()
        assert set(status["known_nodes"]) == {"node_1", "node_2"}

    def test_init_raises_a_clear_error_on_pc(self):
        """
        Calling init() where there is no real radio should raise a clear
        RuntimeError rather than an unrelated AttributeError or crash, so
        server.py's try/except around it can log something useful.
        """
        with pytest.raises(RuntimeError):
            espnow_receiver.init()

    def test_receiver_loop_returns_immediately_on_pc(self):
        """
        receiver_loop() would otherwise run forever. On a platform with no
        espnow module it must return right away instead of hanging the
        test suite.
        """
        import asyncio
        asyncio.run(espnow_receiver.receiver_loop())
        # Reaching this line at all is the assertion, an infinite loop
        # here would time out the test run instead of failing cleanly.
