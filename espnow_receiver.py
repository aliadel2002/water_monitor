# =============================================================================
# espnow_receiver.py
# ESP-NOW receiver for the hub ESP32C3.
#
# This module runs as a background task alongside the MicroDot web server.
# It listens for incoming ESP-NOW packets from moisture sensor nodes and
# updates the central sensor state whenever a node reports a new reading.
#
# HOW IT FITS INTO THE SYSTEM
# ----------------------------
# Moisture Node  -->  (ESP-NOW radio)  -->  Hub ESP32
#                                               |
#                                         espnow_receiver.py
#                                         updates sensor_state.py
#                                               |
#                                         classification.py reads it
#                                               |
#                                         web dashboard shows it
#
# PACKET FORMAT
# -------------
# Each node sends a JSON string over ESP-NOW with two fields:
#
#   {"node_id": "node_1", "wet": true}
#   {"node_id": "node_2", "wet": false}
#
# node_id must match a key in sensor_state.REAL_STATE["moisture_nodes"].
# wet is a boolean — true means water detected, false means dry.
#
# ADDING MORE NODES
# -----------------
# 1. Add the new node ID to sensor_state.py under moisture_nodes
# 2. Flash the node firmware onto a new ESP32 with the correct node_id
# 3. No changes needed here — the receiver handles any node_id automatically
# =============================================================================

import json

# uasyncio is MicroPython's asyncio implementation. On PC it does not
# exist, but CPython's own asyncio has a compatible enough sleep() and
# async def syntax for _handle_packet() to still be imported and unit
# tested there; receiver_loop() itself still only makes sense on real
# hardware with a real radio.
try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

# espnow is a MicroPython built-in module on ESP32 firmware >= 1.19. It does
# not exist on CPython, so this import is guarded the same way ntp_sync.py
# and thingspeak.py guard their platform-specific imports. This lets the
# packet-decoding and validation logic in _handle_packet() be unit tested
# on PC, even though the actual radio calls in init() and receiver_loop()
# only work on real hardware.
try:
    import espnow
    _HAS_ESPNOW = True
except ImportError:
    _HAS_ESPNOW = False

# sensor_state holds the live readings that the web dashboard reads from
import sensor_state

# event_log records when nodes change state
import event_log


# ---------------------------------------------------------------------------
# Module-level ESP-NOW instance
# Initialized once in init() and reused by the receiver loop
# ---------------------------------------------------------------------------
_espnow_instance = None


# ---------------------------------------------------------------------------
# Known node IDs
# Only packets from these node IDs are accepted. Any packet with an
# unrecognised node_id is logged and discarded.
# ---------------------------------------------------------------------------
KNOWN_NODE_IDS = {"node_1", "node_2"}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def init():
    """
    Initialize the ESP-NOW radio on the hub.

    Must be called once before start_receiver_task() is called.
    The Wi-Fi interface must be active before calling this function.

    Raises:
        OSError: if the ESP-NOW hardware cannot be initialized
        RuntimeError: if called on a platform with no espnow module (PC)
    """
    global _espnow_instance

    if not _HAS_ESPNOW:
        raise RuntimeError(
            "espnow module is not available on this platform, "
            "the ESP-NOW receiver only runs on real ESP32 hardware"
        )

    # Create and activate the ESP-NOW instance
    _espnow_instance = espnow.ESPNow()
    _espnow_instance.active(True)

    print("[espnow] Receiver initialized and listening for node packets")


async def receiver_loop():
    """
    Async background task that continuously listens for incoming ESP-NOW
    packets from moisture sensor nodes.

    This function runs forever alongside the MicroDot web server using
    uasyncio. It yields control with await asyncio.sleep(0) on every
    iteration so the web server never gets starved.

    Each received packet is decoded and used to update sensor_state.py.
    Invalid or unrecognised packets are logged and discarded.

    On a platform with no espnow module (PC), this returns immediately
    instead of looping forever, since there is no radio to listen on.
    """
    if not _HAS_ESPNOW:
        print("[espnow] No espnow module on this platform, receiver_loop() is a no-op")
        return

    if _espnow_instance is None:
        print("[espnow] ERROR: init() must be called before receiver_loop()")
        return

    print("[espnow] Receiver loop started")

    while True:
        # irecv() is the async-compatible receive call in MicroPython espnow.
        # It returns None if no packet is waiting, or (mac, data) if one arrived.
        result = _espnow_instance.irecv(0)

        if result is not None:
            mac, raw_data = result
            _handle_packet(mac, raw_data)

        # Yield to other async tasks (web server, classifier) on every loop
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _handle_packet(mac, raw_data):
    """
    Process a single incoming ESP-NOW packet.

    Decodes the JSON payload, validates the node ID, updates the real
    sensor state, and logs any state change.

    Args:
        mac (bytes): MAC address of the sending node (6 bytes)
        raw_data (bytes): raw packet payload from the node
    """
    # Format the MAC address as a readable string for log messages
    mac_str = ":".join("{:02X}".format(b) for b in mac)

    # --- Decode JSON ---
    try:
        packet = json.loads(raw_data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print("[espnow] Bad packet from {}: {}".format(mac_str, e))
        return

    # --- Validate required fields ---
    if "node_id" not in packet or "wet" not in packet:
        print("[espnow] Packet from {} missing fields: {}".format(mac_str, packet))
        return

    node_id = packet["node_id"]
    wet     = bool(packet["wet"])

    # --- Validate node ID ---
    if node_id not in KNOWN_NODE_IDS:
        print("[espnow] Unknown node_id '{}' from {}, ignoring".format(node_id, mac_str))
        return

    # --- Check if state actually changed ---
    # Avoid flooding the event log with repeated identical readings
    nodes         = sensor_state.REAL_STATE["moisture_nodes"]
    current_wet   = nodes[node_id].get("wet", False)
    was_connected = nodes[node_id].get("connected", False)

    state_changed = (wet != current_wet) or (not was_connected)

    # --- Update real sensor state ---
    sensor_state.REAL_STATE["moisture_nodes"][node_id] = {
        "connected": True,   # receiving a packet means the node is connected
        "wet":       wet,
    }

    # --- Log only when something meaningful changed ---
    if state_changed:
        status = "WET" if wet else "dry"
        event_log.add_event(
            "{} reported {} (MAC: {})".format(node_id, status, mac_str)
        )
        print("[espnow] {} -> {}".format(node_id, status))
    else:
        # Print at debug level only, do not flood the event log
        print("[espnow] {} heartbeat (no change)".format(node_id))


def get_status():
    """
    Return a dictionary describing the current ESP-NOW receiver status.
    Used by the web server diagnostics, and by GET /api/espnow/status.

    Returns:
        dict: {"available": bool, "active": bool, "known_nodes": list}

        available is False on any platform with no espnow module (PC),
        regardless of whether init() was ever called. active is only
        meaningful when available is True, and reflects whether init()
        has successfully run on this boot.
    """
    return {
        "available":   _HAS_ESPNOW,
        "active":      _HAS_ESPNOW and _espnow_instance is not None,
        "known_nodes": list(KNOWN_NODE_IDS),
    }
