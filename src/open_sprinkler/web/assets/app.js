"use strict";

const state = {
  status: null,
  schedules: [],
  rainDelay: null,
  history: [],
  refreshTimer: null,
};

const elements = {
  loginDialog: document.querySelector("#login-dialog"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  tokenInput: document.querySelector("#token-input"),
  connectionBadge: document.querySelector("#connection-badge"),
  stopAllButton: document.querySelector("#stop-all-button"),
  controllerTitle: document.querySelector("#controller-title"),
  controllerDetail: document.querySelector("#controller-detail"),
  stationsGrid: document.querySelector("#stations-grid"),
  activeStationMetric: document.querySelector("#active-station-metric"),
  activeUntilMetric: document.querySelector("#active-until-metric"),
  scheduleCountMetric: document.querySelector("#schedule-count-metric"),
  delayBadge: document.querySelector("#delay-badge"),
  delayDetail: document.querySelector("#delay-detail"),
  settingsDialog: document.querySelector("#settings-dialog"),
  settingsDelayBadge: document.querySelector("#settings-delay-badge"),
  settingsDelayDetail: document.querySelector("#settings-delay-detail"),
  scheduleList: document.querySelector("#schedule-list"),
  historyList: document.querySelector("#history-list"),
  scheduleDialog: document.querySelector("#schedule-dialog"),
  scheduleForm: document.querySelector("#schedule-form"),
  scheduleStations: document.querySelector("#schedule-stations"),
  scheduleError: document.querySelector("#schedule-error"),
  toast: document.querySelector("#toast"),
};

function cookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const match = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrfToken = cookie("open_sprinkler_csrf");
    if (csrfToken) headers.set("X-Open-Sprinkler-CSRF", csrfToken);
  }
  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401) {
    showLogin();
    throw new Error("Authentication required");
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload.detail) message = payload.detail;
    } catch (_error) {
      // Keep the HTTP status fallback when no JSON body is available.
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function showLogin() {
  clearInterval(state.refreshTimer);
  if (!elements.loginDialog.open) elements.loginDialog.showModal();
  window.setTimeout(() => elements.tokenInput.focus(), 50);
}

function hideLogin() {
  if (elements.loginDialog.open) elements.loginDialog.close();
  elements.loginForm.reset();
  elements.loginError.textContent = "";
}

function setConnected(connected) {
  elements.connectionBadge.textContent = connected ? "Controller online" : "Controller unavailable";
  elements.connectionBadge.className = `status-pill ${connected ? "online" : "offline"}`;
  elements.connectionBadge.title = connected
    ? "Authenticated and receiving status updates from the local controller"
    : "The browser cannot currently reach the local controller";
}

function formatTime(value) {
  if (!value) return "Not running";
  return new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatDateTime(value) {
  if (!value) return "In progress";
  return new Intl.DateTimeFormat([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function stationName(stationId) {
  return state.status?.stations.find((station) => station.id === stationId)?.name || `Station ${stationId}`;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderStatus() {
  const status = state.status;
  if (!status) return;
  const active = status.stations.find((station) => station.id === status.active_station_id);
  elements.controllerTitle.textContent = active ? `${active.name} is watering` : "Everything is resting";
  elements.controllerDetail.textContent = active
    ? `Automatic stop at ${formatTime(status.active_until)}.`
    : "No station is currently active.";
  elements.activeStationMetric.textContent = active?.name || "None";
  elements.activeUntilMetric.textContent = formatTime(status.active_until);
  elements.stopAllButton.hidden = !active;
  renderStations();
}

function renderStations() {
  elements.stationsGrid.replaceChildren();
  for (const station of state.status?.stations || []) {
    const card = element("article", `station-card${station.active ? " active" : ""}`);
    const top = element("div", "station-card-top");
    const titleGroup = element("div");
    titleGroup.append(element("span", "station-number", `Station ${station.id}`));
    titleGroup.append(element("h3", "", station.name));
    const badge = element("span", `status-pill ${station.active ? "watering" : "neutral"}`, station.active ? "Watering" : "Off");
    top.append(titleGroup, badge);

    const controls = element("div", "station-controls");
    const duration = element("label", "duration-field");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = "120";
    input.value = "10";
    input.setAttribute("aria-label", `${station.name} duration in minutes`);
    duration.append(input, element("span", "", "minutes"));
    const action = element("button", `button ${station.active ? "danger" : "primary"}`, station.active ? "Stop" : "Start");
    action.type = "button";
    action.addEventListener("click", async () => {
      action.disabled = true;
      try {
        if (station.active) {
          await api(`/api/v1/stations/${station.id}/stop`, { method: "POST" });
          notify(`${station.name} stopped`);
        } else {
          const minutes = Number(input.value);
          if (!Number.isFinite(minutes) || minutes < 1 || minutes > 120) throw new Error("Choose 1 to 120 minutes");
          await api(`/api/v1/stations/${station.id}/start`, {
            method: "POST",
            body: JSON.stringify({ duration_seconds: Math.round(minutes * 60) }),
          });
          notify(`${station.name} started`);
        }
        await refreshStatus();
        await refreshHistory();
      } catch (error) {
        notify(error.message, true);
      } finally {
        action.disabled = false;
      }
    });
    controls.append(duration, action);
    card.append(top, controls);
    elements.stationsGrid.append(card);
  }
}

function renderRainDelay() {
  const active = state.rainDelay?.active;
  const detail = active
    ? `Schedules resume ${formatDateTime(state.rainDelay.until)}.`
    : "Scheduled programs may run.";
  elements.delayBadge.textContent = active ? "Schedules paused" : "Schedules active";
  elements.delayBadge.className = `status-pill ${active ? "watering" : "online"}`;
  elements.delayDetail.textContent = detail;
  elements.settingsDelayBadge.textContent = active ? "Rain delay on" : "No delay";
  elements.settingsDelayBadge.className = `status-pill ${active ? "watering" : "online"}`;
  elements.settingsDelayDetail.textContent = detail;
}

function daySummary(days) {
  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  if (days.length === 7) return "Every day";
  return days.map((day) => labels[day]).join(", ");
}

function renderSchedules() {
  elements.scheduleList.replaceChildren();
  elements.scheduleCountMetric.textContent = String(state.schedules.length);
  if (!state.schedules.length) {
    elements.scheduleList.append(element("div", "empty-state", "No schedules yet. Create one when you are ready."));
    return;
  }
  for (const schedule of state.schedules) {
    const card = element("article", "list-card");
    const main = element("div", "list-card-main");
    main.append(element("span", "schedule-time", schedule.start_time.slice(0, 5)));
    const copy = element("div");
    copy.append(element("h3", "", schedule.name));
    const totalMinutes = Math.round(schedule.steps.reduce((total, step) => total + step.duration_seconds, 0) / 60);
    copy.append(element("p", "", `${daySummary(schedule.days_of_week)} · ${schedule.steps.length} stations · ${totalMinutes} min`));
    main.append(copy);

    const actions = element("div", "list-actions");
    const toggle = element("button", `button compact ${schedule.enabled ? "secondary" : "ghost"}`, schedule.enabled ? "Enabled" : "Paused");
    toggle.type = "button";
    toggle.addEventListener("click", async () => {
      try {
        await api(`/api/v1/schedules/${schedule.id}`, {
          method: "PUT",
          body: JSON.stringify({ ...schedule, enabled: !schedule.enabled }),
        });
        await refreshSchedules();
      } catch (error) { notify(error.message, true); }
    });
    const remove = element("button", "button ghost compact", "Delete");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      if (!window.confirm(`Delete ${schedule.name}?`)) return;
      try {
        await api(`/api/v1/schedules/${schedule.id}`, { method: "DELETE" });
        await refreshSchedules();
        notify("Schedule deleted");
      } catch (error) { notify(error.message, true); }
    });
    actions.append(toggle, remove);
    card.append(main, actions);
    elements.scheduleList.append(card);
  }
}

function renderHistory() {
  elements.historyList.replaceChildren();
  if (!state.history.length) {
    elements.historyList.append(element("div", "empty-state", "No watering runs have been recorded yet."));
    return;
  }
  for (const run of state.history) {
    const row = element("article", "history-item");
    const copy = element("div");
    copy.append(element("h3", "", stationName(run.station_id)));
    copy.append(element("p", "", `${formatDateTime(run.started_at)} · ${Math.round(run.duration_seconds / 60)} min · ${run.source}`));
    const outcome = element("span", `status-pill ${run.outcome === "completed" ? "online" : "neutral"}`, run.outcome || "Running");
    row.append(copy, outcome);
    elements.historyList.append(row);
  }
}

function renderScheduleStationOptions() {
  elements.scheduleStations.replaceChildren();
  for (const station of state.status?.stations || []) {
    const row = element("div", "schedule-station-row");
    const label = document.createElement("label");
    const selected = document.createElement("input");
    selected.type = "checkbox";
    selected.dataset.stationId = station.id;
    label.append(selected, document.createTextNode(station.name));
    const duration = document.createElement("input");
    duration.type = "number";
    duration.min = "1";
    duration.max = "120";
    duration.value = "10";
    duration.defaultValue = "10";
    duration.dataset.durationFor = station.id;
    duration.setAttribute("aria-label", `${station.name} duration in minutes`);
    row.append(label, duration);
    elements.scheduleStations.append(row);
  }
}

async function refreshStatus() {
  state.status = await api("/api/v1/status");
  setConnected(true);
  renderStatus();
}

async function refreshSchedules() {
  state.schedules = await api("/api/v1/schedules");
  renderSchedules();
}

async function refreshRainDelay() {
  state.rainDelay = await api("/api/v1/rain-delay");
  renderRainDelay();
}

async function refreshHistory() {
  state.history = await api("/api/v1/history?limit=20");
  renderHistory();
}

async function refreshAll() {
  try {
    await refreshStatus();
    await Promise.all([refreshSchedules(), refreshRainDelay(), refreshHistory()]);
    renderScheduleStationOptions();
    clearInterval(state.refreshTimer);
    state.refreshTimer = window.setInterval(() => refreshStatus().catch(() => setConnected(false)), 5000);
  } catch (error) {
    setConnected(false);
    if (error.message !== "Authentication required") notify(error.message, true);
  }
}

function notify(message, isError = false) {
  elements.toast.textContent = message;
  elements.toast.style.background = isError ? "var(--danger-dark)" : "var(--brand-dark)";
  elements.toast.classList.add("show");
  window.clearTimeout(notify.timer);
  notify.timer = window.setTimeout(() => elements.toast.classList.remove("show"), 3200);
}

elements.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.loginError.textContent = "";
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ token: elements.tokenInput.value }),
    });
    if (!response.ok) throw new Error("The token was not accepted");
    hideLogin();
    await refreshAll();
  } catch (error) {
    elements.loginError.textContent = error.message;
  } finally {
    elements.tokenInput.value = "";
  }
});

elements.stopAllButton.addEventListener("click", async () => {
  try {
    await api("/api/v1/actions/stop-all", { method: "POST" });
    await refreshStatus();
    await refreshHistory();
    notify("All watering stopped");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_error) { /* Session is cleared locally below. */ }
  showLogin();
});

function showSettings() {
  if (!elements.settingsDialog.open) elements.settingsDialog.showModal();
}

document.querySelector("#settings-button").addEventListener("click", showSettings);
document.querySelector("#manage-delay-button").addEventListener("click", showSettings);
document.querySelector("#close-settings-button").addEventListener("click", () => elements.settingsDialog.close());

document.querySelectorAll(".delay-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const until = new Date(Date.now() + Number(button.dataset.hours) * 60 * 60 * 1000);
    try {
      await api("/api/v1/rain-delay", { method: "PUT", body: JSON.stringify({ until: until.toISOString() }) });
      await refreshRainDelay();
      notify(`Rain delay set for ${button.dataset.hours} hours`);
    } catch (error) { notify(error.message, true); }
  });
});

document.querySelector("#clear-delay-button").addEventListener("click", async () => {
  try {
    await api("/api/v1/rain-delay", { method: "DELETE" });
    await refreshRainDelay();
    notify("Rain delay cleared");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#add-schedule-button").addEventListener("click", () => {
  elements.scheduleForm.reset();
  elements.scheduleError.textContent = "";
  elements.scheduleDialog.showModal();
});

document.querySelector("#close-schedule-button").addEventListener("click", () => elements.scheduleDialog.close());
document.querySelector("#cancel-schedule-button").addEventListener("click", () => elements.scheduleDialog.close());
document.querySelector("#refresh-button").addEventListener("click", () => refreshAll());

elements.scheduleForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(elements.scheduleForm);
  const days = form.getAll("day").map(Number);
  const steps = [];
  elements.scheduleStations.querySelectorAll("input[type='checkbox']").forEach((selected) => {
    if (!selected.checked) return;
    const stationId = Number(selected.dataset.stationId);
    const duration = elements.scheduleStations.querySelector(`[data-duration-for='${stationId}']`);
    steps.push({ station_id: stationId, duration_seconds: Math.round(Number(duration.value) * 60) });
  });
  if (!days.length || !steps.length) {
    elements.scheduleError.textContent = "Choose at least one day and one station.";
    return;
  }
  try {
    await api("/api/v1/schedules", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        enabled: true,
        start_time: form.get("start_time"),
        days_of_week: days,
        steps,
      }),
    });
    elements.scheduleDialog.close();
    await refreshSchedules();
    notify("Schedule created");
  } catch (error) {
    elements.scheduleError.textContent = error.message;
  }
});

refreshAll();
