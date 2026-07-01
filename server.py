# =============================================================================
# server.py
# MicroDot web server setup and route registration.
#
# This module:
#   1. Creates the MicroDot app instance
#   2. Registers all REST API routes from api_routes.py
#   3. Serves the single-page dashboard HTML from /static/index.html
#   4. Runs periodic background tasks: classification, daily rollover,
#      NTP re-sync, ThingSpeak cloud logging, and the ESP-NOW receiver
#   5. Starts the server on port 80
#
# To add a new API endpoint, add the handler to api_routes.py and register
# it here with app.route().
# =============================================================================

import uasyncio as asyncio
try:
    from microdot_async import Microdot, Response
except ImportError:
    from microdot import Microdot, Response
import api_routes
import classification
import daily_history
import ntp_sync
import thingspeak
import sensor_state
import espnow_receiver

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


@app.route("/api/history", methods=["GET"])
async def get_history(request):
    return api_routes.handle_get_history(request)


@app.route("/api/analytics", methods=["GET"])
async def get_analytics(request):
    return api_routes.handle_get_analytics(request)


@app.route("/api/time/status", methods=["GET"])
async def get_time_status(request):
    return api_routes.handle_get_time_status(request)


@app.route("/api/time/sync", methods=["POST"])
async def post_time_sync(request):
    return api_routes.handle_post_time_sync(request)


@app.route("/api/cloud/status", methods=["GET"])
async def get_cloud_status(request):
    return api_routes.handle_get_cloud_status(request)


@app.route("/api/cloud/settings", methods=["POST"])
async def post_cloud_settings(request):
    return api_routes.handle_post_cloud_settings(request)


@app.route("/api/cloud/push", methods=["POST"])
async def post_cloud_push(request):
    return api_routes.handle_post_cloud_push(request)


@app.route("/api/ota/status", methods=["GET"])
async def get_ota_status(request):
    return api_routes.handle_get_ota_status(request)


@app.route("/api/ota/check", methods=["POST"])
async def post_ota_check(request):
    return api_routes.handle_post_ota_check(request)


@app.route("/api/ota/apply", methods=["POST"])
async def post_ota_apply(request):
    return api_routes.handle_post_ota_apply(request)


@app.route("/api/ota/reboot", methods=["POST"])
async def post_ota_reboot(request):
    return api_routes.handle_post_ota_reboot(request)


@app.route("/api/espnow/status", methods=["GET"])
async def get_espnow_status(request):
    return api_routes.handle_get_espnow_status(request)


# ---------------------------------------------------------------------------
# Background tasks
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
            print("[classifier] Error: {}".format(e))
        await asyncio.sleep(2)


async def _daily_rollover_loop():
    """
    Check every 60 seconds whether the date has changed, and archive
    yesterday's daily total if so. This relies on the device's clock
    being roughly correct, which is why ntp_sync runs at startup and
    periodically afterward.
    """
    while True:
        try:
            daily_history.check_and_roll_over()
        except Exception as e:
            print("[daily_history] Error: {}".format(e))
        await asyncio.sleep(60)


async def _ntp_resync_loop():
    """
    Re-sync the clock every 6 hours. The ESP32's clock can drift over a
    long uptime, and a fresh sync also protects against a clock that
    never got set correctly on first boot if the network was not ready
    yet at that point.
    """
    while True:
        try:
            ntp_sync.sync()
        except Exception as e:
            print("[ntp_sync] Error: {}".format(e))
        await asyncio.sleep(6 * 60 * 60)


async def _cloud_push_loop():
    """
    Push the current state to ThingSpeak on the interval configured in
    thingspeak.get_config(). Wakes every 5 seconds to re-check the
    configured interval and enabled flag, rather than sleeping for the
    full interval, so a change made through the dashboard takes effect
    quickly.
    """
    last_push = 0
    while True:
        try:
            cfg = thingspeak.get_config()
            if cfg["enabled"]:
                import time
                now = time.time()
                if now - last_push >= cfg["update_interval_sec"]:
                    state = sensor_state.get_active_state()
                    thingspeak.push_update(state)
                    last_push = now
        except Exception as e:
            print("[thingspeak] Error: {}".format(e))
        await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def start_server():
    """
    Start the MicroDot web server and the background tasks (classifier,
    daily rollover check, periodic NTP re-sync, ThingSpeak cloud logging,
    and the ESP-NOW receiver for moisture sensor nodes). This is a
    blocking call, it runs indefinitely.
    """
    print("[server] Starting Water Monitor dashboard on port 80...")

    # Sync the clock once at boot before anything else runs, so the very
    # first day-rollover check has a correct date to compare against.
    ntp_sync.sync()

    # Initialize the ESP-NOW radio for receiving moisture node packets.
    # This assumes the Wi-Fi STA interface is already active, which it
    # must be by this point since the web server itself needs Wi-Fi
    # connectivity to be reachable on port 80. If Wi-Fi connection is
    # handled in boot.py before main.py runs (the usual MicroPython
    # pattern), no extra setup is needed here.
    try:
        espnow_receiver.init()
    except Exception as e:
        print("[server] ESP-NOW init failed, moisture nodes will not be reachable: {}".format(e))

    loop = asyncio.get_event_loop()

    loop.create_task(_classification_loop())
    loop.create_task(_daily_rollover_loop())
    loop.create_task(_ntp_resync_loop())
    loop.create_task(_cloud_push_loop())
    loop.create_task(espnow_receiver.receiver_loop())

    # Start the web server (blocks here)
    app.run(port=80, debug=False)
