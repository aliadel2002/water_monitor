# =============================================================================
# server_pc.py
# PC-compatible version of server.py for testing without an ESP32.
#
# Differences from server.py:
#   - Uses Flask instead of MicroDot
#   - Uses Python's built-in threading instead of uasyncio
#   - Serves static files from ./static/ folder
#   - Runs on http://localhost:5000 http://127.0.0.1:5000/
#
# To run:
#   1. pip install flask
#   2. python server_pc.py
#   3. Open http://localhost:5000
# python server_pc.py
# http://127.0.0.1:5000
# =============================================================================

import threading
import time
from flask import Flask, request, send_from_directory, Response
import api_routes
import classification
import daily_history
import ntp_sync
import thingspeak
import sensor_state

app = Flask(__name__, static_folder="static")


# ---------------------------------------------------------------------------
# Serve static files (index.html, dashboard.js, etc.)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main dashboard HTML file."""
    return send_from_directory("static", "index.html")


@app.route("/static/<filename>")
def static_files(filename):
    """Serve any file from the ./static/ folder."""
    return send_from_directory("static", filename)


# ---------------------------------------------------------------------------
# Request wrapper — makes Flask requests compatible with api_routes.py
# ---------------------------------------------------------------------------

class _RequestWrapper:
    """
    Wraps a Flask request so api_routes handlers can read request.body
    the same way they would on MicroDot.
    """
    def __init__(self, flask_request):
        self.body = flask_request.data


def _flask_response(result):
    """Convert a (body, status, headers) tuple into a Flask Response."""
    body, status, headers = result
    return Response(body, status=status, headers=headers)


# ---------------------------------------------------------------------------
# REST API routes
# ---------------------------------------------------------------------------

@app.route("/api/state", methods=["GET"])
def get_state():
    return _flask_response(api_routes.handle_get_state(_RequestWrapper(request)))

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return _flask_response(api_routes.handle_get_settings(_RequestWrapper(request)))

@app.route("/api/settings", methods=["POST"])
def post_settings():
    return _flask_response(api_routes.handle_post_settings(_RequestWrapper(request)))

@app.route("/api/reset-alarm", methods=["POST"])
def reset_alarm():
    return _flask_response(api_routes.handle_reset_alarm(_RequestWrapper(request)))

@app.route("/api/mode", methods=["GET"])
def get_mode():
    return _flask_response(api_routes.handle_get_mode(_RequestWrapper(request)))

@app.route("/api/mode", methods=["POST"])
def post_mode():
    return _flask_response(api_routes.handle_post_mode(_RequestWrapper(request)))

@app.route("/api/test/update", methods=["POST"])
def test_update():
    return _flask_response(api_routes.handle_test_update(_RequestWrapper(request)))

@app.route("/api/test/scenario", methods=["POST"])
def test_scenario():
    return _flask_response(api_routes.handle_test_scenario(_RequestWrapper(request)))

@app.route("/api/test/scenarios", methods=["GET"])
def get_scenarios():
    return _flask_response(api_routes.handle_get_scenarios(_RequestWrapper(request)))

@app.route("/api/test/reset", methods=["POST"])
def test_reset():
    return _flask_response(api_routes.handle_test_reset(_RequestWrapper(request)))

@app.route("/api/events", methods=["GET"])
def get_events():
    return _flask_response(api_routes.handle_get_events(_RequestWrapper(request)))

@app.route("/api/events/clear", methods=["POST"])
def clear_events():
    return _flask_response(api_routes.handle_clear_events(_RequestWrapper(request)))

@app.route("/api/history", methods=["GET"])
def get_history():
    return _flask_response(api_routes.handle_get_history(_RequestWrapper(request)))

@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    return _flask_response(api_routes.handle_get_analytics(_RequestWrapper(request)))

@app.route("/api/time/status", methods=["GET"])
def get_time_status():
    return _flask_response(api_routes.handle_get_time_status(_RequestWrapper(request)))

@app.route("/api/time/sync", methods=["POST"])
def post_time_sync():
    return _flask_response(api_routes.handle_post_time_sync(_RequestWrapper(request)))

@app.route("/api/cloud/status", methods=["GET"])
def get_cloud_status():
    return _flask_response(api_routes.handle_get_cloud_status(_RequestWrapper(request)))

@app.route("/api/cloud/settings", methods=["POST"])
def post_cloud_settings():
    return _flask_response(api_routes.handle_post_cloud_settings(_RequestWrapper(request)))

@app.route("/api/cloud/push", methods=["POST"])
def post_cloud_push():
    return _flask_response(api_routes.handle_post_cloud_push(_RequestWrapper(request)))

@app.route("/api/ota/status", methods=["GET"])
def get_ota_status():
    return _flask_response(api_routes.handle_get_ota_status(_RequestWrapper(request)))

@app.route("/api/ota/check", methods=["POST"])
def post_ota_check():
    return _flask_response(api_routes.handle_post_ota_check(_RequestWrapper(request)))

@app.route("/api/ota/apply", methods=["POST"])
def post_ota_apply():
    return _flask_response(api_routes.handle_post_ota_apply(_RequestWrapper(request)))

@app.route("/api/ota/reboot", methods=["POST"])
def post_ota_reboot():
    return _flask_response(api_routes.handle_post_ota_reboot(_RequestWrapper(request)))

@app.route("/api/espnow/status", methods=["GET"])
def get_espnow_status():
    return _flask_response(api_routes.handle_get_espnow_status(_RequestWrapper(request)))


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------
# Three periodic jobs run on their own threads on PC (uasyncio tasks on the
# ESP32, see server.py). Each is wrapped in its own try/except so a failure
# in one (for example, a network error in the ThingSpeak push) can never
# stop the others or crash the process.

def _classification_loop():
    """Run the classifier every 2 seconds in a background thread."""
    while True:
        try:
            classification.classify()
        except Exception as e:
            print(f"[classifier] Error: {e}")
        time.sleep(2)


def _daily_rollover_loop():
    """
    Check every 60 seconds whether the date has changed, and archive
    yesterday's total if so. Checking once a minute is frequent enough to
    catch the midnight boundary promptly without doing real work most of
    the time it runs.
    """
    while True:
        try:
            daily_history.check_and_roll_over()
        except Exception as e:
            print(f"[daily_history] Error: {e}")
        time.sleep(60)


def _cloud_push_loop():
    """
    Push the current state to ThingSpeak on the interval configured in
    thingspeak.get_config(). This loop wakes up every 5 seconds just to
    re-check whether the configured interval has elapsed and whether
    logging is still enabled, rather than sleeping for the full interval,
    so a change to the interval or an enable/disable toggle takes effect
    quickly instead of waiting out a long stale sleep.
    """
    last_push = 0.0
    while True:
        try:
            cfg = thingspeak.get_config()
            if cfg["enabled"]:
                now = time.time()
                if now - last_push >= cfg["update_interval_sec"]:
                    state = sensor_state.get_active_state()
                    thingspeak.push_update(state)
                    last_push = now
        except Exception as e:
            print(f"[thingspeak] Error: {e}")
        time.sleep(5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[server_pc] Starting Water Monitor dashboard...")
    print("[server_pc] Open http://127.0.0.1:5000 in your browser")
    print("[server_pc] Press Ctrl+C to stop\n")

    # The system clock on PC is already correct, so this just records
    # that fact through ntp_sync's no-op path.
    ntp_sync.sync()

    threading.Thread(target=_classification_loop, daemon=True).start()
    threading.Thread(target=_daily_rollover_loop, daemon=True).start()
    threading.Thread(target=_cloud_push_loop, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=False)
