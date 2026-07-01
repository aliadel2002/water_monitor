
// ============================================================================
// dashboard.js  (inlined)
// All client-side logic for the Water Monitor dashboard.
//
// Sections:
//   1. Tab navigation
//   2. API helpers
//   3. State rendering - update the DOM from a state payload
//   4. Event log rendering
//   5. Polling loop - fetch /api/state every 3 seconds
//   6. Dashboard tab - alarm reset, manual refresh
//   7. Sensors tab - rendering helper
//   8. Test mode tab - mode switch, scenario loader, manual input apply
//   9. Settings tab - save settings
//  10. System tab - time sync, cloud logging, OTA updates
//  11. Init - run on page load
// ============================================================================


// ============================================================================
// 1. TAB NAVIGATION
// ============================================================================

/**
 * Activate the tab whose data-tab attribute matches `name`.
 * Deactivates all other tabs and panels.
 */
function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach(panel => {
    panel.classList.toggle("active", panel.id === "tab-" + name);
  });
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});


// ============================================================================
// 2. API HELPERS
// ============================================================================

/**
 * Perform a GET request and return the parsed JSON body.
 * Throws on non-2xx status.
 */
async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

/**
 * Perform a POST request with a JSON body and return the parsed JSON body.
 * Throws on non-2xx status.
 */
async function apiPost(path, body) {
  const res = await fetch(path, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `POST ${path} failed: ${res.status}`);
  return data;
}

/**
 * Show a feedback message inside a given element.
 * Automatically hides after 4 seconds.
 *
 * @param {string} id   - id of the feedback <div>
 * @param {string} msg  - message to display
 * @param {boolean} ok  - true = success style, false = error style
 */
function showFeedback(id, msg, ok) {
  const el = document.getElementById(id);
  el.textContent   = msg;
  el.className     = "feedback " + (ok ? "success" : "error");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.className = "feedback"; }, 4000);
}


// ============================================================================
// 3. STATE RENDERING
// Accepts the JSON payload from GET /api/state and updates the DOM.
// ============================================================================

/**
 * Map a system_state string to a human-readable description.
 */
const STATE_DESCRIPTIONS = {
  normal:         "All sensors reading normal. No leaks detected.",
  warning:        "Usage is approaching the daily limit. Consider reducing water use.",
  abnormal:       "Abnormal flow detected. Acoustic sensor indicates a possible hidden leak.",
  leak_alarm:     "Leak alarm - a moisture sensor has detected water. Check the location immediately.",
  confirmed_leak: "Leak confirmed - water has been detected continuously past the confirmation window. Treat this as an active leak.",
};

/**
 * Map a system_state string to a display label.
 */
const STATE_LABELS = {
  normal:         "Normal",
  warning:        "Warning",
  abnormal:       "Abnormal flow",
  leak_alarm:     "Leak alarm",
  confirmed_leak: "Leak confirmed",
};

/**
 * Render the full dashboard from a state payload.
 * Called by the polling loop and after any action that changes state.
 *
 * @param {object} s - parsed JSON from GET /api/state
 */
function renderState(s) {
  // --- Mode badge ---
  const badge = document.getElementById("mode-badge");
  badge.textContent = s.mode === "test" ? "TEST" : "LIVE";
  badge.className   = "mode-badge " + s.mode;

  // --- System state badge ---
  const stateBadge = document.getElementById("state-badge");
  stateBadge.className = "state-badge " + s.system_state;
  document.getElementById("state-text").textContent =
    STATE_LABELS[s.system_state] || s.system_state;
  document.getElementById("state-description").textContent =
    STATE_DESCRIPTIONS[s.system_state] || "";

  // --- Alarm reset button, visible in leak_alarm and confirmed_leak ---
  document.getElementById("alarm-actions").style.display =
    (s.system_state === "leak_alarm" || s.system_state === "confirmed_leak")
      ? "block" : "none";

  // --- Flow and usage metrics ---
  document.getElementById("flow-rate").textContent    = s.flow_rate_lpm.toFixed(1);
  document.getElementById("daily-total").textContent  = s.daily_total_litres.toFixed(1);
  document.getElementById("daily-limit-display").textContent =
    s.daily_limit_litres.toFixed(0);

  // --- Usage bar ---
  const pct     = Math.min(s.usage_pct, 100);
  const bar     = document.getElementById("usage-bar");
  const remaining = Math.max(0, s.daily_limit_litres - s.daily_total_litres);

  bar.style.width = pct + "%";
  bar.className   = "usage-bar-fill" +
    (pct >= 100 ? " danger" : pct >= s.warning_threshold_pct ? " warning" : "");

  document.getElementById("usage-label").textContent =
    pct.toFixed(1) + "% used";
  document.getElementById("usage-remaining").textContent =
    remaining.toFixed(1) + " L remaining";

  // --- Sensors tab ---
  renderSensors(s);

  // --- Sync settings inputs if they have not been changed by the user ---
  document.getElementById("daily-limit-display").textContent =
    s.daily_limit_litres.toFixed(0);
}

/**
 * Render the 7-day analytics card (rolling average, eco score, streak)
 * and the archived usage history list.
 *
 * @param {object} a - parsed JSON from GET /api/analytics
 * @param {Array}  h - parsed JSON from GET /api/history
 */
function renderAnalytics(a, h) {
  document.getElementById("analytics-avg").textContent    = a.rolling_average_litres.toFixed(1);
  document.getElementById("analytics-eco").textContent    = a.eco_score;
  document.getElementById("analytics-streak").textContent = a.streak_days;

  const list = document.getElementById("history-list");
  if (!h || h.length === 0) {
    list.textContent = "No archived days yet. History fills in after the first midnight rollover.";
    return;
  }

  // Show the most recent entries first, newest at the top.
  const rows = h.slice().reverse().map(entry =>
    `<div style="display:flex; justify-content:space-between; padding:3px 0;">
       <span>${escapeHtml(entry.date)}</span>
       <span>${entry.total_litres.toFixed(1)} L</span>
     </div>`
  );
  list.innerHTML = rows.join("");
}


// ============================================================================
// 4. EVENT LOG RENDERING
// ============================================================================

/**
 * Render the event log from an array of event objects.
 * Timestamps are generated here in the browser using the local clock.
 *
 * Each event object: { id: number, message: string }
 * The browser stamps each entry with the current local time when it
 * renders it. Entries already rendered (by id) are not re-added.
 */
const _renderedEventIds = new Set();

function renderEvents(events) {
  const container = document.getElementById("event-log");

  // Add new entries (newest first at the top)
  let added = false;
  events.forEach(ev => {
    if (_renderedEventIds.has(ev.id)) return;
    _renderedEventIds.add(ev.id);

    const now  = new Date();
    const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    const entry = document.createElement("div");
    entry.className = "event-entry";
    entry.innerHTML =
      `<span class="event-time">${time}</span>` +
      `<span class="event-message">${escapeHtml(ev.message)}</span>`;

    // Prepend so newest is at the top
    container.insertBefore(entry, container.firstChild);
    added = true;
  });

  // If the log was cleared on the server, clear it here too
  if (events.length === 0 && container.children.length > 0) {
    container.innerHTML = "";
    _renderedEventIds.clear();
  }
}

/** Escape HTML special characters to prevent injection. */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}


// ============================================================================
// 5. POLLING LOOP
// Fetches /api/state and /api/events every 3 seconds.
// ============================================================================

let _pollingInterval = null;

/**
 * Fetch the current state and events from the server and update the DOM.
 * Errors are caught silently so a temporary connection drop does not crash
 * the dashboard.
 */
async function poll() {
  try {
    const [state, events] = await Promise.all([
      apiGet("/api/state"),
      apiGet("/api/events"),
    ]);
    renderState(state);
    renderEvents(events);
  } catch (err) {
    console.warn("[poll] Failed to reach server:", err.message);
  }
}

/**
 * Fetch and render the analytics card and usage history. These only
 * change once a day at most (when the daily rollover happens), so this
 * runs far less often than the main state poll rather than on the same
 * 3 second interval.
 */
async function pollAnalytics() {
  try {
    const [analyticsData, history, espnowStatus] = await Promise.all([
      apiGet("/api/analytics"),
      apiGet("/api/history"),
      apiGet("/api/espnow/status"),
    ]);
    renderAnalytics(analyticsData, history);
    renderEspnowStatus(espnowStatus);
  } catch (err) {
    console.warn("[pollAnalytics] Failed to reach server:", err.message);
  }
}

/**
 * Render the ESP-NOW receiver status line on the Sensors tab.
 *
 * @param {object} status - parsed JSON from GET /api/espnow/status
 */
function renderEspnowStatus(status) {
  const el = document.getElementById("espnow-status");
  if (!status.available) {
    el.textContent = "not available on this platform";
  } else if (status.active) {
    el.textContent = "active, listening for " + status.known_nodes.join(", ");
  } else {
    el.textContent = "available but not yet initialized";
  }
}

function startPolling() {
  poll(); // run immediately on load
  pollAnalytics();
  _pollingInterval = setInterval(poll, 3000);
  setInterval(pollAnalytics, 60000);
}


// ============================================================================
// 6. DASHBOARD TAB — alarm reset, manual refresh
// ============================================================================

document.getElementById("btn-reset-alarm").addEventListener("click", async () => {
  try {
    const res = await apiPost("/api/reset-alarm", {});
    showFeedback("reset-feedback", res.message, true);
    poll();
  } catch (err) {
    showFeedback("reset-feedback", err.message, false);
  }
});

document.getElementById("btn-refresh").addEventListener("click", () => poll());

document.getElementById("btn-clear-log").addEventListener("click", async () => {
  try {
    await apiPost("/api/events/clear", {});
    document.getElementById("event-log").innerHTML = "";
    _renderedEventIds.clear();
  } catch (err) {
    console.warn("Could not clear log:", err.message);
  }
});


// ============================================================================
// 7. SENSORS TAB — rendering helper
// ============================================================================

/**
 * Render the moisture nodes and acoustic sensor cards on the Sensors tab.
 * Called as part of renderState so it stays in sync with polling.
 *
 * @param {object} s - parsed state payload
 */
function renderSensors(s) {
  // --- Moisture nodes ---
  const moistureGrid = document.getElementById("moisture-nodes-grid");
  moistureGrid.innerHTML = "";

  Object.entries(s.moisture_nodes).forEach(([name, node]) => {
    const label = name === "node_1" ? "Node 1" : "Node 2";
    let statusClass, statusText;

    if (!node.connected) {
      statusClass = "not-connected";
      statusText  = "Not connected";
    } else if (node.wet) {
      statusClass = "wet";
      statusText  = "WET — leak detected";
    } else {
      statusClass = "ok";
      statusText  = "Dry — OK";
    }

    moistureGrid.innerHTML +=
      `<div class="sensor-card">
         <div class="sensor-card-name">${label}</div>
         <div class="sensor-status ${statusClass}">${statusText}</div>
       </div>`;
  });

  // --- Acoustic sensor ---
  const acGrid = document.getElementById("acoustic-sensor-grid");
  const ac = s.acoustic_sensor;

  if (!ac.connected) {
    acGrid.innerHTML =
      `<div class="sensor-card">
         <div class="sensor-card-name">Vibration sensor</div>
         <div class="sensor-status not-connected">Not connected</div>
         <div style="font-size:11px; color:var(--text-dim); margin-top:6px;">
           Component not yet selected. Will be available after hardware integration.
         </div>
       </div>`;
  } else {
    const anomalyClass = ac.anomaly ? "wet" : "ok";
    const anomalyText  = ac.anomaly ? "Anomaly detected" : "Normal";
    acGrid.innerHTML =
      `<div class="sensor-card">
         <div class="sensor-card-name">Vibration sensor</div>
         <div class="sensor-status ${anomalyClass}">${anomalyText}</div>
         <div style="font-size:11px; color:var(--text-dim); margin-top:6px;">
           RMS: ${ac.signal_rms.toFixed(3)}
         </div>
       </div>`;
  }

  // --- Flow sensor status ---
  document.getElementById("flow-sensor-detail").textContent =
    s.flow_rate_lpm.toFixed(2) + " L/min";
}


// ============================================================================
// 8. TEST MODE TAB
// ============================================================================

// --- Enter / exit test mode ---
document.getElementById("btn-enter-test").addEventListener("click", async () => {
  try {
    await apiPost("/api/mode", { mode: "test" });
    showFeedback("mode-feedback", "Test mode active. Real sensor data is unaffected.", true);
    poll();
  } catch (err) {
    showFeedback("mode-feedback", err.message, false);
  }
});

document.getElementById("btn-exit-test").addEventListener("click", async () => {
  try {
    await apiPost("/api/mode", { mode: "real" });
    showFeedback("mode-feedback", "Switched back to live data.", true);
    poll();
  } catch (err) {
    showFeedback("mode-feedback", err.message, false);
  }
});

// --- Load preset scenarios from the server and build the scenario grid ---
async function loadScenarios() {
  try {
    const scenarios = await apiGet("/api/test/scenarios");
    const grid = document.getElementById("scenario-grid");
    grid.innerHTML = "";

    scenarios.forEach(sc => {
      const btn = document.createElement("button");
      btn.className = "scenario-btn";
      btn.innerHTML =
        `<span class="sc-label">${escapeHtml(sc.label)}</span>` +
        `<span class="sc-desc">${escapeHtml(sc.description)}</span>`;

      btn.addEventListener("click", async () => {
        try {
          await apiPost("/api/test/scenario", { scenario: sc.name });
          showFeedback("test-feedback", `Scenario "${sc.label}" applied.`, true);
          poll();
        } catch (err) {
          showFeedback("test-feedback", err.message, false);
        }
      });

      grid.appendChild(btn);
    });
  } catch (err) {
    console.warn("Could not load scenarios:", err.message);
  }
}

// --- Apply manual inputs ---
document.getElementById("btn-apply-manual").addEventListener("click", async () => {
  const payload = {
    flow_rate_lpm:      parseFloat(document.getElementById("input-flow-rate").value)  || 0,
    daily_total_litres: parseFloat(document.getElementById("input-daily-total").value) || 0,
    node_1_connected:   document.getElementById("chk-n1-connected").checked,
    node_1_wet:         document.getElementById("chk-n1-wet").checked,
    node_2_connected:   document.getElementById("chk-n2-connected").checked,
    node_2_wet:         document.getElementById("chk-n2-wet").checked,
    acoustic_connected: document.getElementById("chk-ac-connected").checked,
    acoustic_anomaly:   document.getElementById("chk-ac-anomaly").checked,
    acoustic_signal_rms: parseFloat(document.getElementById("input-ac-rms").value) || 0,
  };

  try {
    const res = await apiPost("/api/test/update", payload);
    showFeedback("test-feedback", `Values applied. State: ${res.system_state}`, true);
    poll();
  } catch (err) {
    showFeedback("test-feedback", err.message, false);
  }
});

// --- Reset test state ---
document.getElementById("btn-reset-test").addEventListener("click", async () => {
  try {
    await apiPost("/api/test/reset", {});
    showFeedback("test-feedback", "Test state reset to defaults.", true);
    poll();
  } catch (err) {
    showFeedback("test-feedback", err.message, false);
  }
});


// ============================================================================
// 9. SETTINGS TAB
// ============================================================================

/** Populate the settings inputs from the server on load. */
async function loadSettings() {
  try {
    const cfg = await apiGet("/api/settings");
    document.getElementById("setting-limit").value        = cfg.daily_limit_litres;
    document.getElementById("setting-warn-pct").value     = cfg.warning_threshold_pct;
    document.getElementById("setting-confirm-sec").value  = cfg.confirmed_leak_threshold_sec;
  } catch (err) {
    console.warn("Could not load settings:", err.message);
  }
}

document.getElementById("btn-save-settings").addEventListener("click", async () => {
  const limit      = parseFloat(document.getElementById("setting-limit").value);
  const warnPct    = parseFloat(document.getElementById("setting-warn-pct").value);
  const confirmSec = parseFloat(document.getElementById("setting-confirm-sec").value);

  try {
    await apiPost("/api/settings", {
      daily_limit_litres:            limit,
      warning_threshold_pct:         warnPct,
      confirmed_leak_threshold_sec:  confirmSec,
    });
    showFeedback("settings-feedback", "Settings saved.", true);
    poll(); // refresh the usage bar to reflect the new limit
  } catch (err) {
    showFeedback("settings-feedback", err.message, false);
  }
});


// ============================================================================
// 10. SYSTEM TAB — time sync, cloud logging, OTA updates
// ============================================================================

/** Populate the clock sync display from the server. */
async function loadTimeStatus() {
  try {
    const status = await apiGet("/api/time/status");
    document.getElementById("time-source").textContent =
      status.source === "ntp" ? "Synced via NTP" : "Using system clock";
    document.getElementById("time-last-sync").textContent =
      status.last_sync_time ? new Date(status.last_sync_time * 1000).toLocaleString() : "never";
  } catch (err) {
    console.warn("Could not load time status:", err.message);
  }
}

document.getElementById("btn-time-sync").addEventListener("click", async () => {
  try {
    await apiPost("/api/time/sync", {});
    showFeedback("time-feedback", "Clock synced.", true);
    loadTimeStatus();
  } catch (err) {
    showFeedback("time-feedback", err.message, false);
  }
});

/** Populate the cloud logging inputs from the server. */
async function loadCloudSettings() {
  try {
    const cfg = await apiGet("/api/cloud/status");
    document.getElementById("chk-cloud-enabled").checked  = cfg.enabled;
    document.getElementById("input-cloud-key").value      = cfg.api_key;
    document.getElementById("input-cloud-interval").value = cfg.update_interval_sec;
  } catch (err) {
    console.warn("Could not load cloud settings:", err.message);
  }
}

document.getElementById("btn-cloud-save").addEventListener("click", async () => {
  const enabled  = document.getElementById("chk-cloud-enabled").checked;
  const apiKey   = document.getElementById("input-cloud-key").value.trim();
  const interval = parseFloat(document.getElementById("input-cloud-interval").value);

  try {
    await apiPost("/api/cloud/settings", {
      enabled:              enabled,
      api_key:              apiKey,
      update_interval_sec:  interval,
    });
    showFeedback("cloud-feedback", "Cloud logging settings saved.", true);
  } catch (err) {
    showFeedback("cloud-feedback", err.message, false);
  }
});

document.getElementById("btn-cloud-push").addEventListener("click", async () => {
  try {
    const res = await apiPost("/api/cloud/push", {});
    if (res.sent) {
      showFeedback("cloud-feedback", "Push sent to ThingSpeak.", true);
    } else {
      showFeedback("cloud-feedback", "Not sent: " + res.reason, false);
    }
  } catch (err) {
    showFeedback("cloud-feedback", err.message, false);
  }
});

/** Populate the firmware version display from the server. */
async function loadOtaStatus() {
  try {
    const status = await apiGet("/api/ota/status");
    document.getElementById("ota-current-version").textContent = status.current_version;
    document.getElementById("btn-ota-apply").disabled = !status.update_available;
  } catch (err) {
    console.warn("Could not load OTA status:", err.message);
  }
}

document.getElementById("btn-ota-check").addEventListener("click", async () => {
  const manifestUrl = document.getElementById("input-ota-manifest").value.trim();
  if (!manifestUrl) {
    showFeedback("ota-feedback", "Enter a manifest URL first.", false);
    return;
  }

  try {
    const res = await apiPost("/api/ota/check", { manifest_url: manifestUrl });
    document.getElementById("btn-ota-apply").disabled = !res.update_available;
    if (res.update_available) {
      showFeedback("ota-feedback",
        `Update available: ${res.current_version} -> ${res.candidate_version}`, true);
    } else {
      showFeedback("ota-feedback",
        `Already up to date (${res.current_version}).`, true);
    }
  } catch (err) {
    showFeedback("ota-feedback", err.message, false);
  }
});

document.getElementById("btn-ota-apply").addEventListener("click", async () => {
  try {
    const res = await apiPost("/api/ota/apply", {});
    showFeedback("ota-feedback",
      "Update applied. Files written: " + res.files_written.join(", "), true);
    document.getElementById("btn-ota-apply").disabled  = true;
    document.getElementById("btn-ota-reboot").disabled = false;
    loadOtaStatus();
  } catch (err) {
    showFeedback("ota-feedback", err.message, false);
  }
});

document.getElementById("btn-ota-reboot").addEventListener("click", async () => {
  try {
    await apiPost("/api/ota/reboot", {});
    showFeedback("ota-feedback", "Reboot requested.", true);
  } catch (err) {
    showFeedback("ota-feedback", err.message, false);
  }
});


// ============================================================================
// 11. INIT — runs once on page load
// ============================================================================

(async function init() {
  await loadSettings();
  await loadScenarios();
  await loadTimeStatus();
  await loadCloudSettings();
  await loadOtaStatus();
  startPolling();
})();
