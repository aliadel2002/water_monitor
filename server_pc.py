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
# =============================================================================

import threading
import time
from flask import Flask, request, send_from_directory, Response
import api_routes
import classification

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


# ---------------------------------------------------------------------------
# Background classification loop
# ---------------------------------------------------------------------------

def _classification_loop():
    """Run the classifier every 2 seconds in a background thread."""
    while True:
        try:
            classification.classify()
        except Exception as e:
            print(f"[classifier] Error: {e}")
        time.sleep(2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[server_pc] Starting Water Monitor dashboard...")
    print("[server_pc] Open http://127.0.0.1:5000 in your browser")
    print("[server_pc] Press Ctrl+C to stop\n")

    t = threading.Thread(target=_classification_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, debug=False)
