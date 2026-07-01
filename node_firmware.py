# =============================================================================
# node_firmware.py
# Firmware for each individual moisture sensor node ESP32.
#
# SETUP INSTRUCTIONS
# ------------------
# 1. Flash MicroPython onto the node ESP32 board
# 2. Change NODE_ID below to a unique name for this node:
#       "node_1" for the first node
#       "node_2" for the second node
# 3. Change HUB_MAC below to the MAC address of your hub ESP32C3.
#    To find the hub MAC address, run this on the hub once:
#
#       import network
#       wlan = network.WLAN(network.STA_IF)
#       wlan.active(True)
#       print(wlan.config('mac'))
#
#    Then convert each byte to hex. For example if the output is:
#       b'\xaa\xbb\xcc\xdd\xee\xff'
#    Set HUB_MAC = b'\xaa\xbb\xcc\xdd\xee\xff'
#
# 4. Connect the moisture sensor signal pin to the GPIO pin defined in
#    MOISTURE_PIN below. The sensor outputs HIGH when wet, LOW when dry
#    (or the reverse depending on your module — adjust WET_SIGNAL_LEVEL).
#
# 5. Upload this file as main.py onto the node ESP32.
#    It will run automatically every time the node wakes from deep sleep.
#
# HOW IT WORKS
# ------------
# The node wakes up, reads the moisture sensor, sends one ESP-NOW packet
# to the hub, then goes back to deep sleep for SLEEP_INTERVAL_MS milliseconds.
# This cycle repeats indefinitely, keeping the node very low power.
#
# Deep sleep current draw on ESP32 is typically 10-150 µA depending on
# the board, compared to ~80 mA when awake. With a 5 second sleep interval
# the node is awake for roughly 200 ms per cycle — about 4% of the time.
# =============================================================================

import machine
import network
import espnow
import json
import time


# =============================================================================
# CONFIGURATION — change these values for each node
# =============================================================================

# Unique identifier for this node. Must match a key in sensor_state.py.
# Options: "node_1" or "node_2"
NODE_ID = "node_1"

# MAC address of the hub ESP32C3.
# Replace with the actual bytes from your hub's MAC address.
# Example: b'\xaa\xbb\xcc\xdd\xee\xff'
HUB_MAC = b'\x00\x00\x00\x00\x00\x00'   # <-- REPLACE THIS

# GPIO pin connected to the moisture sensor signal output
MOISTURE_PIN = 4

# Signal level that means WET. Most FC-37 modules output HIGH when wet.
# If your sensor reads backwards, change this to 0.
WET_SIGNAL_LEVEL = 1

# How long to sleep between readings, in milliseconds.
# 5000 ms = 5 seconds. Shorter = faster response, shorter battery life.
SLEEP_INTERVAL_MS = 5000

# How many milliseconds to wait for ESP-NOW to confirm packet delivery.
# If the hub is not responding, the node gives up after this timeout.
SEND_TIMEOUT_MS = 500


# =============================================================================
# MAIN SEQUENCE — runs once on every wake-up from deep sleep
# =============================================================================

def read_moisture():
    """
    Read the moisture sensor and return True if wet, False if dry.

    The pin is configured with an internal pull resistor so that a
    disconnected sensor reads as dry rather than wet. Which resistor to
    use depends on WET_SIGNAL_LEVEL: if wet means HIGH, the pin needs a
    pull-down so a floating pin defaults LOW (dry); if wet means LOW, it
    needs a pull-up so a floating pin defaults HIGH (dry). Hard-coding
    PULL_DOWN regardless of WET_SIGNAL_LEVEL would make a disconnected
    sensor read as a false wet whenever WET_SIGNAL_LEVEL is set to 0,
    which defeats the point of having a pull resistor at all.

    Returns:
        bool: True if the sensor is detecting moisture, False if dry
    """
    pull = machine.Pin.PULL_DOWN if WET_SIGNAL_LEVEL == 1 else machine.Pin.PULL_UP
    pin = machine.Pin(MOISTURE_PIN, machine.Pin.IN, pull)

    # Small delay to let the pin stabilize after configuration
    time.sleep_ms(10)

    raw_value = pin.value()
    is_wet = (raw_value == WET_SIGNAL_LEVEL)

    print("[node] Moisture pin value: {} -> {}".format(raw_value, "WET" if is_wet else "dry"))
    return is_wet


def init_espnow():
    """
    Initialize ESP-NOW on the node.

    ESP-NOW requires the Wi-Fi interface to be active, but the node does
    NOT connect to a Wi-Fi network — it just uses the radio hardware.
    This is important for battery life: no DHCP, no association, no beacon
    listening. Just the raw radio layer.

    Returns:
        espnow.ESPNow: initialized and active ESP-NOW instance
    """
    # Activate the Wi-Fi station interface (required for ESP-NOW hardware)
    # but do NOT connect to any network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    # Initialize ESP-NOW
    e = espnow.ESPNow()
    e.active(True)

    # Register the hub as a peer so we can send packets to it
    # add_peer(mac, channel) — channel 0 means use the current channel
    try:
        e.add_peer(HUB_MAC)
        print(f"[node] Hub registered as peer")
    except OSError as err:
        # Peer may already be registered from a previous wake cycle
        print(f"[node] add_peer: {err} (may already be registered)")

    return e


def send_packet(e, is_wet):
    """
    Send a moisture reading packet to the hub over ESP-NOW.

    The packet is a JSON string containing the node ID and wet status.
    JSON is used so the hub can easily decode it regardless of byte order
    or struct layout differences between different ESP32 boards.

    Args:
        e (espnow.ESPNow): active ESP-NOW instance
        is_wet (bool): True if moisture detected, False if dry

    Returns:
        bool: True if the packet was sent successfully, False on error
    """
    payload = {
        "node_id": NODE_ID,
        "wet":     is_wet,
    }

    packet_bytes = json.dumps(payload).encode("utf-8")

    try:
        e.send(HUB_MAC, packet_bytes)
        print(f"[node] Packet sent: {payload}")
        return True
    except OSError as err:
        print(f"[node] Send failed: {err}")
        return False


def go_to_sleep():
    """
    Put the ESP32 into deep sleep for SLEEP_INTERVAL_MS milliseconds.

    Deep sleep powers down almost everything on the chip except the
    RTC (real-time clock) which handles the wake-up timer. After the
    sleep interval, the chip resets and main.py runs from the beginning
    again — there is no "resume", just a fresh start each cycle.
    """
    print(f"[node] Going to deep sleep for {SLEEP_INTERVAL_MS} ms")
    machine.deepsleep(SLEEP_INTERVAL_MS)
    # Code after this line never runs — deepsleep() does not return


def run():
    """
    Main entry point. Runs the full sense -> send -> sleep cycle once.

    Called automatically when the node wakes from deep sleep.
    After go_to_sleep() is called, the chip resets and run() is called
    again on the next wake cycle.
    """
    print(f"\n[node] Wake cycle start — node_id: {NODE_ID}")

    # Step 1: Read the moisture sensor
    is_wet = read_moisture()

    # Step 2: Initialize ESP-NOW radio
    e = init_espnow()

    # Step 3: Send the reading to the hub
    success = send_packet(e, is_wet)

    if not success:
        print("[node] WARNING: packet delivery failed — hub may be offline")

    # Step 4: Deactivate ESP-NOW before sleeping to ensure clean shutdown
    e.active(False)

    # Step 5: Go to deep sleep until next reading interval
    go_to_sleep()


# Run the main cycle
run()
