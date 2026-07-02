# Water Leak and Usage Monitoring System: Software Module

Back-end and firmware software for a residential water leak and usage
monitoring system, built as part of a senior capstone project at the
University of Pittsburgh. This repository covers the software and
back-end layer only. Ultrasonic flow sensing (TDC1000/TDC7200) and
acoustic/vibration anomaly detection (FFT processing) are owned by other
team members and are not part of this module.

## What this system does

A central hub (a Seeed XIAO ESP32C3) reads live sensor data, classifies
the current state of the plumbing system, logs events, and serves a web
dashboard so a homeowner can watch usage and get alerted to leaks in real
time. The same Python codebase runs two ways:

- **On the ESP32**, using MicroPython and the MicroDot web framework
- **On a PC**, using CPython and Flask, for development and automated
  testing without any hardware attached

Both versions share the exact same state, classification, and API logic.
Only the two server files (`server.py` for the ESP32, `server_pc.py` for
PC) differ, and they differ only in how they wire the web framework and
background tasks together, not in what the system actually does.

## Architecture

The system is organized into seven layers:

| Layer | Purpose | Status |
|---|---|---|
| 1. Hardware abstraction | GPIO, SPI, PWM, sensor drivers | Flow and acoustic drivers owned by other team members. Moisture node firmware is in this module. |
| 2. FSM / core logic | Classification into normal, warning, abnormal, leak_alarm, confirmed_leak | Complete |
| 3. UI / feedback | Not used. The web dashboard replaces a physical OLED, RGB LED, and rotary encoder. | N/A by design |
| 4. Persistence | Settings, daily totals, and history survive a reboot | Complete |
| 5. Analytics / gamification | 7-day rolling average, eco score, usage streak | Complete |
| 6. Web server / dashboard | REST API plus a single-page dashboard | Complete |
| 7. IoT / cloud | NTP time sync, ThingSpeak logging, OTA updates | Complete, with caveats noted below |

## Repository structure

```
water_monitor/
├── main.py                 entry point for the ESP32, calls start_server()
├── server.py               MicroDot routes and background tasks (ESP32)
├── server_pc.py            Flask routes and background threads (PC)
├── api_routes.py           all REST API handler functions, framework independent
├── sensor_state.py         central state store (REAL_STATE and TEST_STATE)
├── settings.py             user-configurable settings, persisted to flash/disk
├── classification.py       system state classifier, runs every 2 seconds
├── event_log.py            in-memory event log, capped at 50 entries
├── clock.py                shared time source, with a test-only override hook
├── persistence.py          shared JSON file storage for flash and PC disk
├── daily_history.py        midnight rollover and archived daily totals
├── analytics.py            7-day average, eco score, usage streak
├── ntp_sync.py              clock sync, real NTP on ESP32, no-op on PC
├── thingspeak.py           optional cloud logging, off by default
├── ota.py                  manifest-based firmware updater
├── espnow_receiver.py      hub-side ESP-NOW listener for moisture nodes
├── node_firmware.py        firmware flashed onto each moisture sensor node
├── test_api.py             pytest suite for the REST API and core logic
├── test_espnow.py          pytest suite for ESP-NOW packet handling
└── static/
    ├── index.html          dashboard page markup and styling
    └── dashboard.js        all dashboard JavaScript
```

## Running on PC

```
pip install flask pytest pytest-flask
cd water_monitor
python server_pc.py
```

Open `http://127.0.0.1:5000` in a browser.

To run the automated tests:

```
pytest test_api.py -v
pytest test_espnow.py -v
```

`test_espnow.py` only exercises the packet-decoding logic in
`espnow_receiver.py`. The actual radio calls only work on real ESP32
hardware and are not covered by these tests.

Note that `requests` is intentionally not in the install list above.
`thingspeak.py` and `ota.py` both fall back gracefully with no crash and
no test failures when it is missing, since cloud logging and OTA updates
are optional features, off by default.

## Running on the ESP32

1. Flash MicroPython onto the XIAO ESP32C3.
2. Upload every `.py` file in this repository except `server_pc.py`,
   `node_firmware.py`, `test_api.py`, and `test_espnow.py`, along with the
   `static/` folder, to the device's flash filesystem.
3. Upload `main.py` as the entry point.
4. Make sure the device connects to Wi-Fi before `main.py` runs (typically
   handled in a `boot.py` file, not included here since Wi-Fi credentials
   are environment specific).
5. Power on the device. The dashboard will be reachable on port 80 at
   whatever IP address the device receives from your router.

## Moisture sensor nodes

Each moisture sensor node is a separate ESP32 running `node_firmware.py`,
flashed as its own `main.py`. Before uploading to a node:

1. Set `NODE_ID` to `"node_1"` or `"node_2"`.
2. Set `HUB_MAC` to the hub's Wi-Fi station MAC address.
3. Confirm `WET_SIGNAL_LEVEL` matches your specific moisture sensor
   module (most read HIGH when wet, some read LOW).

Nodes wake from deep sleep, take one reading, send it to the hub over
ESP-NOW, and go back to sleep, repeating every `SLEEP_INTERVAL_MS`
milliseconds. This keeps them low power, since the radio is only active
for a fraction of a second per cycle.

## System states

The classifier evaluates conditions in this priority order, highest
priority first:

1. **confirmed_leak**: a moisture node has read wet continuously for at
   least `confirmed_leak_threshold_sec` seconds (default 300)
2. **leak_alarm**: a moisture node is currently wet, but not yet long
   enough to confirm
3. **abnormal**: flow is active while the acoustic sensor reports an
   anomaly
4. **warning**: daily usage has crossed the configured warning
   threshold percentage of the daily limit
5. **normal**: everything else

A leak alarm can only be reset once all moisture nodes read dry. Resetting
also clears the confirmation timer, so a new leak starts its own count
rather than inheriting time from a previous one.

## REST API

All endpoints return JSON. A representative subset:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/state` | GET | Full system state and computed usage percentage |
| `/api/settings` | GET / POST | Read or update daily limit, warning threshold, confirmation window |
| `/api/reset-alarm` | POST | Reset a leak alarm once dry |
| `/api/mode` | GET / POST | Switch between real and test sensor data |
| `/api/test/update`, `/api/test/scenario` | POST | Inject sensor values or apply a preset scenario, no hardware needed |
| `/api/events` | GET | Recent event log entries |
| `/api/history` | GET | Archived daily usage totals |
| `/api/analytics` | GET | 7-day average, eco score, usage streak |
| `/api/time/status`, `/api/time/sync` | GET / POST | Clock sync status, manual sync |
| `/api/cloud/status`, `/api/cloud/settings`, `/api/cloud/push` | GET / POST | ThingSpeak configuration and manual push |
| `/api/ota/status`, `/api/ota/check`, `/api/ota/apply`, `/api/ota/reboot` | GET / POST | Firmware update check and apply |
| `/api/espnow/status` | GET | Whether the ESP-NOW receiver is available and active |

Every handler in `api_routes.py` is a plain function that takes a request
object and returns `(body, status_code, headers)`. Neither Flask nor
MicroDot appear inside that file, which is what lets the exact same
handler code run on both platforms.

## Known limitations

- **OTA updates** are a simple file-overwrite mechanism, not a true
  dual-partition scheme. A bad download or a power loss mid-write can
  leave the device unable to boot until it is reflashed over USB. A
  production system would write to an inactive flash partition and only
  switch over after verifying a successful boot.
- **ESP-NOW** has not been tested on real hardware yet. The hub-side
  receiver and the node firmware have been reviewed for logic correctness
  and the packet-handling logic is unit tested on PC, but the actual
  radio behavior can only be confirmed with physical boards.
- **Flow rate and acoustic anomaly detection** depend on sensor drivers
  owned by other team members and are outside this module's scope.

## Team

Software and back-end development for this module by Ali Morsy, computer
engineering, University of Pittsburgh. Ultrasonic flow sensing and
acoustic signal processing are developed by other members of the
three-person capstone team.
