# =============================================================================
# server.py
# MicroDot web server setup and route registration.
#
# This module:
#   1. Creates the MicroDot app instance
#   2. Registers all REST API routes from api_routes.py
#   3. Serves the single-page dashboard HTML from /static/index.html
#   4. Runs a periodic background task that calls the classifier every 2s
#   5. Starts the server on port 80
#
# To add a new API endpoint, add the handler to api_routes.py and register
# it here with app.route().
# =============================================================================

import uasyncio as asyncio
from microdot import Microdot, Response
import api_routes
import classification

# Allow larger request bodies (needed for test mode JSON payloads)
Response.default_content_type = "text/html"

app = Microdot()


# ---------------------------------------------------------------------------
# Serve the dashboard HTML page
# ---------------------------------------------------------------------------

@app.route("/")
async def index(request):
    """Serve the main dashboard HTML file from flash storage."""
    try:
        with open("/static/index.html", "r") as f:
            html = f.read()
        return html, 200, {"Content-Type": "text/html"}
    except OSError:
        return "Dashboard file not found. Upload /static/index.html to the ESP32.", 404


# ---------------------------------------------------------------------------
# REST API routes — all delegate to api_routes.py handler functions
# ---------------------------------------------------------------------------

@app.route("/api/state", methods=["GET"])
async def get_state(request):
    return api_routes.handle_get_state(request)


@app.route("/api/settings", methods=["GET"])
async def get_settings(request):
    return api_routes.handle_get_settings(request)


@app.route("/api/settings", methods=["POST"])
async def post_settings(request):
    return api_routes.handle_post_settings(request)


@app.route("/api/reset-alarm", methods=["POST"])
async def reset_alarm(request):
    return api_routes.handle_reset_alarm(request)


@app.route("/api/mode", methods=["GET"])
async def get_mode(request):
    return api_routes.handle_get_mode(request)


@app.route("/api/mode", methods=["POST"])
async def post_mode(request):
    return api_routes.handle_post_mode(request)


@app.route("/api/test/update", methods=["POST"])
async def test_update(request):
    return api_routes.handle_test_update(request)


@app.route("/api/test/scenario", methods=["POST"])
async def test_scenario(request):
    return api_routes.handle_test_scenario(request)


@app.route("/api/test/scenarios", methods=["GET"])
async def get_scenarios(request):
    return api_routes.handle_get_scenarios(request)


@app.route("/api/test/reset", methods=["POST"])
async def test_reset(request):
    return api_routes.handle_test_reset(request)


@app.route("/api/events", methods=["GET"])
async def get_events(request):
    return api_routes.handle_get_events(request)


@app.route("/api/events/clear", methods=["POST"])
async def clear_events(request):
    return api_routes.handle_clear_events(request)


# ---------------------------------------------------------------------------
# Background classification task
# ---------------------------------------------------------------------------

async def _classification_loop():
    """
    Run the classifier every 2 seconds in the background.
    This keeps the system state up to date without blocking the web server.
    """
    while True:
        try:
            classification.classify()
        except Exception as e:
            # Log but do not crash — the server must keep running
            print(f"[classifier] Error: {e}")
        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def start_server():
    """
    Start the MicroDot web server and the background classification loop.
    This is a blocking call — it runs indefinitely.
    """
    print("[server] Starting Water Monitor dashboard on port 80...")

    loop = asyncio.get_event_loop()

    # Schedule the background classifier
    loop.create_task(_classification_loop())

    # Start the web server (blocks here)
    app.run(port=80, debug=False)
