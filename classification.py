# =============================================================================
# classification.py
# System state classification algorithm.
#
# This module reads the active sensor state and the current settings, then
# determines the overall system state. It is the single place where the
# logic "what does this sensor data mean?" lives.
#
# States (in order of priority, highest first):
#   "leak_alarm"  — one or more moisture nodes are wet
#   "abnormal"    — flow detected with no expected usage AND acoustic anomaly
#   "warning"     — daily usage has crossed the warning threshold percentage
#   "normal"      — everything is within expected parameters
#
# The classifier is called periodically by the server's background task,
# not on every sensor read, to keep CPU usage low.
# =============================================================================

import event_log
import sensor_state
import settings


# Track the previous state separately for each mode so switching between
# real and test mode does not trigger false state-change log entries
_previous_state = {"real": "normal", "test": "normal"}


def classify():
    """
    Read the active sensor state and settings, determine the system state,
    log any state transition, and write the new state back into the active
    state dictionary.

    Returns:
        str: the newly determined system state
    """
    mode = sensor_state.get_mode()

    state  = sensor_state.get_active_state()
    cfg    = settings.get_settings()
    nodes  = state["moisture_nodes"]
    daily  = state["daily_total_litres"]
    limit  = cfg["daily_limit_litres"]
    thresh = cfg["warning_threshold_pct"]

    # ------------------------------------------------------------------
    # Priority 1: Leak alarm
    # ------------------------------------------------------------------
    wet_nodes = [name for name, n in nodes.items() if n.get("wet")]
    if wet_nodes:
        new_state = "leak_alarm"

    # ------------------------------------------------------------------
    # Priority 2: Abnormal usage
    # ------------------------------------------------------------------
    elif (state["flow_rate_lpm"] > 0
          and state["acoustic_sensor"]["connected"]
          and state["acoustic_sensor"]["anomaly"]):
        new_state = "abnormal"

    # ------------------------------------------------------------------
    # Priority 3: Warning
    # ------------------------------------------------------------------
    elif limit > 0 and (daily / limit * 100) >= thresh:
        new_state = "warning"

    # ------------------------------------------------------------------
    # Priority 4: Normal
    # ------------------------------------------------------------------
    else:
        new_state = "normal"

    # ------------------------------------------------------------------
    # Log only when the state changes within the current mode
    # ------------------------------------------------------------------
    if new_state != _previous_state[mode]:
        _log_transition(_previous_state[mode], new_state, wet_nodes)
        _previous_state[mode] = new_state

    # Write the result back into the active state
    if mode == "test":
        sensor_state.TEST_STATE["system_state"] = new_state
    else:
        sensor_state.REAL_STATE["system_state"] = new_state

    return new_state


def _log_transition(old_state, new_state, wet_nodes):
    """
    Log a human-readable message describing the state change.

    Args:
        old_state (str): previous system state
        new_state (str): new system state
        wet_nodes (list): list of node names that are currently wet
    """
    if new_state == "leak_alarm":
        node_str = ", ".join(wet_nodes)
        event_log.add_event(
            f"Leak alarm triggered — wet sensor(s): {node_str}"
        )
    elif new_state == "abnormal":
        event_log.add_event(
            "Abnormal flow detected — acoustic anomaly while flow is active"
        )
    elif new_state == "warning":
        event_log.add_event(
            "Usage warning — approaching daily limit"
        )
    elif new_state == "normal" and old_state != "normal":
        event_log.add_event(
            f"System returned to normal (was: {old_state})"
        )
