# =============================================================================
# sensor_state.py
# Central state store for all sensor readings and system status.
#
# This module holds two separate state objects:
#   - REAL_STATE  : populated by actual sensor drivers (flow, moisture, acoustic)
#   - TEST_STATE  : populated by the user through the Test Mode dashboard tab
#
# The rest of the system always reads from ACTIVE_STATE, which points to
# whichever of the two is currently active. Switching between real and test
# mode never touches the real sensor data.
# =============================================================================


# ---------------------------------------------------------------------------
# Default values used when the system first boots
# ---------------------------------------------------------------------------
_DEFAULT_STATE = {
    # --- Flow sensor ---
    "flow_rate_lpm":     0.0,    # Current flow rate in litres per minute
    "daily_total_litres": 0.0,   # Total water used today in litres

    # --- System classification ---
    # Possible values: "normal" | "abnormal" | "leak_alarm" | "confirmed_leak"
    # Daily usage warning is surfaced separately via the usage_exceeded field
    # in /api/state and does NOT change system_state.
    "system_state": "normal",

    # --- Moisture sensor nodes ---
    # Each entry: {"connected": bool, "wet": bool}
    "moisture_nodes": {
        "node_1": {"connected": False, "wet": False},
        "node_2": {"connected": False, "wet": False},
    },

    # --- Acoustic sensor ---
    # connected: False until a sensor component is selected and wired
    "acoustic_sensor": {
        "connected": False,
        "signal_rms": 0.0,       # RMS amplitude of vibration signal
        "anomaly": False,        # True if an anomalous pattern is detected
    },
}


def _copy_default():
    """Return a fresh deep copy of the default state dictionary."""
    import json
    return json.loads(json.dumps(_DEFAULT_STATE))


# ---------------------------------------------------------------------------
# The two state objects
# ---------------------------------------------------------------------------

# Real sensor state — written to by sensor driver modules only
REAL_STATE = _copy_default()

# Test state — written to by the Test Mode API endpoints only
TEST_STATE = _copy_default()

# Which state is currently active: "real" or "test"
_active_mode = "real"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_active_state():
    """
    Return the currently active state dictionary.
    All read operations in the system should call this function.
    """
    if _active_mode == "test":
        return TEST_STATE
    return REAL_STATE


def set_mode(mode):
    """
    Switch the active state between real sensor data and test data.

    Args:
        mode (str): "real" or "test"

    Raises:
        ValueError: if mode is not one of the two valid strings
    """
    global _active_mode
    if mode not in ("real", "test"):
        raise ValueError("mode must be 'real' or 'test'")
    _active_mode = mode


def get_mode():
    """Return the current active mode string: 'real' or 'test'."""
    return _active_mode


def update_real_sensor(key, value):
    """
    Update a top-level key in the real sensor state.
    Called by sensor driver modules (flow sensor, moisture nodes, etc.).

    Args:
        key (str): top-level key in the state dictionary
        value: new value
    """
    REAL_STATE[key] = value


def update_test_sensor(key, value):
    """
    Update a top-level key in the test state.
    Called by the Test Mode API endpoint when the user changes dummy values.

    Args:
        key (str): top-level key in the state dictionary
        value: new value
    """
    TEST_STATE[key] = value


def reset_test_state():
    """Reset the test state back to all default values."""
    global TEST_STATE
    TEST_STATE = _copy_default()
