"use strict";

const state = {
  status: null,
  schedules: [],
  rainDelay: null,
  weather: null,
  controllerSettings: null,
  history: [],
  editingScheduleId: null,
  refreshTimer: null,
  countdownTimer: null,
};

const elements = {
  loginDialog: document.querySelector("#login-dialog"),
  loginForm: document.querySelector("#login-form"),
  loginError: document.querySelector("#login-error"),
  tokenInput: document.querySelector("#token-input"),
  connectionBadge: document.querySelector("#connection-badge"),
  weatherButton: document.querySelector("#weather-button"),
  stopAllButton: document.querySelector("#stop-all-button"),
  stopActionLabel: document.querySelector("#stop-action-label"),
  controllerTitle: document.querySelector("#controller-title"),
  controllerDetail: document.querySelector("#controller-detail"),
  holdStatus: document.querySelector("#hold-status"),
  stationsGrid: document.querySelector("#stations-grid"),
  activeStationMetric: document.querySelector("#active-station-metric"),
  activeUntilMetric: document.querySelector("#active-until-metric"),
  scheduleCountMetric: document.querySelector("#schedule-count-metric"),
  delayBadge: document.querySelector("#delay-badge"),
  delayDetail: document.querySelector("#delay-detail"),
  settingsDialog: document.querySelector("#settings-dialog"),
  settingsDelayBadge: document.querySelector("#settings-delay-badge"),
  settingsDelayDetail: document.querySelector("#settings-delay-detail"),
  clearDelayButton: document.querySelector("#clear-delay-button"),
  customDelayHours: document.querySelector("#custom-delay-hours"),
  weatherForm: document.querySelector("#weather-form"),
  weatherFormError: document.querySelector("#weather-form-error"),
  weatherSettingsBadge: document.querySelector("#weather-settings-badge"),
  weatherCurrent: document.querySelector("#weather-current"),
  weatherForecast: document.querySelector("#weather-forecast"),
  controllerSettingsForm: document.querySelector("#controller-settings-form"),
  controllerStations: document.querySelector("#controller-stations"),
  controllerSettingsError: document.querySelector("#controller-settings-error"),
  controllerRestartNotice: document.querySelector("#controller-restart-notice"),
  scheduleList: document.querySelector("#schedule-list"),
  historyList: document.querySelector("#history-list"),
  scheduleDialog: document.querySelector("#schedule-dialog"),
  scheduleForm: document.querySelector("#schedule-form"),
  scheduleStations: document.querySelector("#schedule-stations"),
  scheduleError: document.querySelector("#schedule-error"),
  scheduleHeading: document.querySelector("#schedule-form-heading"),
  scheduleEyebrow: document.querySelector("#schedule-form-eyebrow"),
  scheduleSubmitButton: document.querySelector("#schedule-submit-button"),
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
  clearInterval(state.countdownTimer);
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

function formatCountdown(value) {
  const remaining = Math.max(0, Math.ceil((new Date(value).getTime() - Date.now()) / 1000));
  const hours = Math.floor(remaining / 3600);
  const minutes = Math.floor((remaining % 3600) / 60);
  const seconds = remaining % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function updateCountdowns() {
  document.querySelectorAll("[data-countdown-until]").forEach((input) => {
    input.value = formatCountdown(input.dataset.countdownUntil);
  });
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
  const stopAction = state.controllerSettings?.stop_action || "schedule";
  elements.stopActionLabel.textContent = stopAction === "station"
    ? "Stop current station"
    : stopAction === "day"
      ? "Stop watering for today"
      : status.active_source === "schedule"
        ? "Stop current schedule"
        : "Stop current station";
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
    if (station.active && state.status.active_until) {
      input.type = "text";
      input.readOnly = true;
      input.dataset.countdownUntil = state.status.active_until;
      input.value = formatCountdown(state.status.active_until);
      input.setAttribute("aria-label", `${station.name} remaining watering time`);
      duration.append(input, element("span", "", "remaining"));
    } else {
      input.type = "number";
      input.min = "1";
      input.max = String(state.controllerSettings?.max_duration_minutes || 120);
      input.value = "10";
      input.setAttribute("aria-label", `${station.name} duration in minutes`);
      duration.append(input, element("span", "", "minutes"));
    }
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
          const maximum = state.controllerSettings?.max_duration_minutes || 120;
          if (!Number.isFinite(minutes) || minutes < 1 || minutes > maximum) throw new Error(`Choose 1 to ${maximum} minutes`);
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
  const sources = state.rainDelay?.sources || [];
  const sourceName = sources.length > 1
    ? "Manual and weather holds"
    : sources[0] === "weather" ? "Weather hold" : "Manual hold";
  const detail = active
    ? `${sourceName} until ${formatDateTime(state.rainDelay.until)}.`
    : "Scheduled programs may run.";
  elements.delayBadge.textContent = active ? "Schedules paused" : "Schedules active";
  elements.delayBadge.className = `status-pill ${active ? "watering" : "online"}`;
  elements.delayDetail.textContent = detail;
  elements.settingsDelayBadge.textContent = active ? "Rain delay on" : "No delay";
  elements.settingsDelayBadge.className = `status-pill ${active ? "watering" : "online"}`;
  const settingsDetails = [];
  if (state.rainDelay?.manual_until) settingsDetails.push(`Manual until ${formatDateTime(state.rainDelay.manual_until)}.`);
  if (state.rainDelay?.weather_until) settingsDetails.push(`Weather until ${formatDateTime(state.rainDelay.weather_until)}.`);
  elements.settingsDelayDetail.textContent = settingsDetails.join(" ") || detail;
  elements.clearDelayButton.disabled = !state.rainDelay?.manual_until;
  elements.holdStatus.hidden = !active;
  elements.holdStatus.textContent = active ? detail : "";
}

function weatherDescription(code) {
  if (code === 0) return "Clear";
  if ([1, 2].includes(code)) return "Partly cloudy";
  if (code === 3) return "Overcast";
  if ([45, 48].includes(code)) return "Fog";
  if ([51, 53, 55, 56, 57].includes(code)) return "Drizzle";
  if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return "Rain";
  if ([71, 73, 75, 77, 85, 86].includes(code)) return "Snow";
  if ([95, 96, 99].includes(code)) return "Storms";
  return "Weather";
}

function weatherIcon(code) {
  if (code === 0) return "☀";
  if ([1, 2].includes(code)) return "⛅";
  if ([3, 45, 48].includes(code)) return "☁";
  if ([71, 73, 75, 77, 85, 86].includes(code)) return "❄";
  if ([95, 96, 99].includes(code)) return "⛈";
  return "☂";
}

function renderWeather() {
  const weather = state.weather;
  if (!weather) return;
  const enabled = weather.settings.enabled;
  elements.weatherSettingsBadge.textContent = enabled ? (weather.available ? "Active" : "Unavailable") : "Off";
  elements.weatherSettingsBadge.className = `status-pill ${enabled && weather.available ? "online" : "neutral"}`;
  elements.weatherForecast.replaceChildren();

  if (!enabled) {
    elements.weatherButton.textContent = "Weather off";
    elements.weatherCurrent.textContent = "Weather automation is off.";
    return;
  }
  if (!weather.available) {
    elements.weatherButton.textContent = "Weather unavailable";
    elements.weatherCurrent.textContent = weather.error || "Waiting for the first weather update.";
    return;
  }

  const today = weather.daily[0];
  const future = weather.daily[1] || today;
  const futureDay = new Intl.DateTimeFormat([], { weekday: "short" }).format(new Date(`${future.date}T12:00:00`));
  elements.weatherButton.textContent = `${weatherIcon(weather.weather_code)} ${Math.round(weather.temperature_f)}° · ${futureDay} ${future.precipitation_probability}%`;
  elements.weatherButton.title = `${weatherDescription(weather.weather_code)} now. ${future.precipitation_probability}% precipitation chance ${futureDay}.`;
  elements.weatherCurrent.textContent = `${weather.settings.location_name}: ${Math.round(weather.temperature_f)}°F and ${weatherDescription(weather.weather_code).toLowerCase()}. Evaluated precipitation: ${(weather.evaluated_precipitation_inches || 0).toFixed(2)} in.`;
  for (const day of weather.daily.slice(0, 4)) {
    const card = element("article", "forecast-card");
    const dayName = new Intl.DateTimeFormat([], { weekday: "short" }).format(new Date(`${day.date}T12:00:00`));
    card.append(
      element("strong", "", dayName),
      element("span", "forecast-icon", weatherIcon(day.weather_code)),
      element("span", "", `${Math.round(day.temperature_max_f)}° / ${Math.round(day.temperature_min_f)}°`),
      element("small", "muted", `${day.precipitation_probability}% · ${day.precipitation_inches.toFixed(2)} in`),
    );
    elements.weatherForecast.append(card);
  }
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
    const edit = element("button", "button ghost compact", "Edit");
    edit.type = "button";
    edit.addEventListener("click", () => openScheduleDialog(schedule));
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
    actions.append(edit, toggle, remove);
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
    duration.max = String(state.controllerSettings?.max_duration_minutes || 120);
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

async function refreshWeather() {
  try {
    state.weather = await api("/api/v1/weather");
    renderWeather();
  } catch (error) {
    if (error.message === "Weather automation is not configured") {
      state.weather = null;
      elements.weatherButton.textContent = "Weather unavailable";
      return;
    }
    throw error;
  }
}

async function refreshControllerSettings() {
  state.controllerSettings = await api("/api/v1/controller-settings");
  renderControllerSettings();
  renderStatus();
}

async function refreshHistory() {
  state.history = await api("/api/v1/history?limit=20");
  renderHistory();
}

async function refreshAll() {
  try {
    await refreshStatus();
    await Promise.all([refreshSchedules(), refreshRainDelay(), refreshWeather(), refreshControllerSettings(), refreshHistory()]);
    renderScheduleStationOptions();
    clearInterval(state.refreshTimer);
    clearInterval(state.countdownTimer);
    state.refreshTimer = window.setInterval(() => {
      Promise.all([refreshStatus(), refreshRainDelay(), refreshWeather()]).catch(() => setConnected(false));
    }, 5000);
    state.countdownTimer = window.setInterval(updateCountdowns, 1000);
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
    const result = await api("/api/v1/actions/configured-stop", { method: "POST" });
    await refreshStatus();
    await refreshRainDelay();
    await refreshHistory();
    notify(result.action === "day" ? "Watering paused until tomorrow" : "Watering stopped");
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try { await api("/api/v1/auth/logout", { method: "POST" }); } catch (_error) { /* Session is cleared locally below. */ }
  showLogin();
});

function populateWeatherForm() {
  const settings = state.weather?.settings;
  if (!settings) return;
  document.querySelector("#weather-enabled").checked = settings.enabled;
  document.querySelector("#weather-postal-code").value = settings.postal_code || "";
  document.querySelector("#weather-latitude").value = settings.latitude ?? "";
  document.querySelector("#weather-longitude").value = settings.longitude ?? "";
  document.querySelector("#weather-threshold").value = settings.precipitation_threshold_inches;
  document.querySelector("#weather-delay-hours").value = settings.delay_hours_after_precipitation;
}

function renderControllerSettings() {
  const settings = state.controllerSettings;
  if (!settings) return;
  elements.controllerStations.replaceChildren();
  for (const station of settings.stations) {
    const row = element("div", "controller-station-row");
    row.append(element("strong", "", `#${station.id}`));
    const nameLabel = element("label", "", "Station name");
    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 100;
    name.required = true;
    name.value = station.name;
    name.dataset.stationName = station.id;
    nameLabel.append(name);
    const pinLabel = element("label", "", "BCM GPIO");
    const pin = document.createElement("input");
    pin.type = "number";
    pin.min = "0";
    pin.max = "27";
    pin.required = true;
    pin.value = station.gpio_pin;
    pin.dataset.stationPin = station.id;
    pinLabel.append(pin);
    row.append(nameLabel, pinLabel);
    elements.controllerStations.append(row);
  }
  document.querySelector("#controller-timezone").value = settings.timezone;
  document.querySelector("#controller-max-duration").value = settings.max_duration_minutes;
  document.querySelector("#controller-stop-action").value = settings.stop_action;
  elements.controllerRestartNotice.hidden = !settings.restart_required;
}

function showSettings(section = null) {
  populateWeatherForm();
  renderControllerSettings();
  if (!elements.settingsDialog.open) elements.settingsDialog.showModal();
  if (section) window.setTimeout(() => section.scrollIntoView({ block: "start" }), 20);
}

document.querySelector("#settings-button").addEventListener("click", () => showSettings());
document.querySelector("#manage-delay-button").addEventListener("click", () => showSettings());
elements.weatherButton.addEventListener("click", () => showSettings(document.querySelector("#weather-settings-section")));
document.querySelector("#close-settings-button").addEventListener("click", () => elements.settingsDialog.close());

elements.controllerSettingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.controllerSettingsError.textContent = "";
  const stations = state.controllerSettings.stations.map((station) => ({
    id: station.id,
    name: elements.controllerStations.querySelector(`[data-station-name='${station.id}']`).value.trim(),
    gpio_pin: Number(elements.controllerStations.querySelector(`[data-station-pin='${station.id}']`).value),
  }));
  try {
    state.controllerSettings = await api("/api/v1/controller-settings", {
      method: "PUT",
      body: JSON.stringify({
        stations,
        timezone: document.querySelector("#controller-timezone").value.trim(),
        max_duration_minutes: Number(document.querySelector("#controller-max-duration").value),
        stop_action: document.querySelector("#controller-stop-action").value,
      }),
    });
    renderControllerSettings();
    await refreshStatus();
    renderScheduleStationOptions();
    notify(state.controllerSettings.restart_required ? "Settings saved. Restart required for GPIO changes." : "Controller settings saved");
  } catch (error) {
    elements.controllerSettingsError.textContent = error.message;
  }
});

async function setManualDelay(hours) {
  const until = new Date(Date.now() + hours * 60 * 60 * 1000);
  await api("/api/v1/rain-delay", { method: "PUT", body: JSON.stringify({ until: until.toISOString() }) });
  await refreshRainDelay();
}

document.querySelectorAll(".delay-button").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await setManualDelay(Number(button.dataset.hours));
      notify(`Rain delay set for ${button.dataset.hours} hours`);
    } catch (error) { notify(error.message, true); }
  });
});

document.querySelector("#set-custom-delay-button").addEventListener("click", async () => {
  const hours = Number(elements.customDelayHours.value);
  if (!Number.isFinite(hours) || hours < 1 || hours > 336) {
    notify("Choose a custom delay from 1 to 336 hours", true);
    return;
  }
  try {
    await setManualDelay(hours);
    notify(`Rain delay set for ${hours} hours`);
  } catch (error) { notify(error.message, true); }
});

document.querySelector("#clear-delay-button").addEventListener("click", async () => {
  try {
    await api("/api/v1/rain-delay", { method: "DELETE" });
    await refreshRainDelay();
    notify("Manual hold cleared");
  } catch (error) { notify(error.message, true); }
});

elements.weatherForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.weatherFormError.textContent = "";
  const valueOrNull = (selector) => {
    const value = document.querySelector(selector).value.trim();
    return value === "" ? null : Number(value);
  };
  try {
    state.weather = await api("/api/v1/weather/settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: document.querySelector("#weather-enabled").checked,
        postal_code: document.querySelector("#weather-postal-code").value.trim(),
        latitude: valueOrNull("#weather-latitude"),
        longitude: valueOrNull("#weather-longitude"),
        precipitation_threshold_inches: Number(document.querySelector("#weather-threshold").value),
        delay_hours_after_precipitation: Number(document.querySelector("#weather-delay-hours").value),
      }),
    });
    renderWeather();
    populateWeatherForm();
    await refreshRainDelay();
    notify("Weather settings saved");
  } catch (error) {
    elements.weatherFormError.textContent = error.message;
  }
});

document.querySelector("#refresh-weather-button").addEventListener("click", async () => {
  try {
    state.weather = await api("/api/v1/weather/refresh", { method: "POST" });
    renderWeather();
    await refreshRainDelay();
    notify(state.weather.error ? state.weather.error : "Weather updated", Boolean(state.weather.error));
  } catch (error) { notify(error.message, true); }
});

function openScheduleDialog(schedule = null) {
  state.editingScheduleId = schedule?.id ?? null;
  elements.scheduleForm.reset();
  renderScheduleStationOptions();
  elements.scheduleError.textContent = "";
  elements.scheduleHeading.textContent = schedule ? "Edit schedule" : "Create schedule";
  elements.scheduleEyebrow.textContent = schedule ? "Update automation" : "New automation";
  elements.scheduleSubmitButton.textContent = schedule ? "Save changes" : "Create schedule";
  if (schedule) {
    elements.scheduleForm.elements.name.value = schedule.name;
    elements.scheduleForm.elements.start_time.value = schedule.start_time.slice(0, 5);
    for (const day of schedule.days_of_week) {
      elements.scheduleForm.querySelector(`input[name='day'][value='${day}']`).checked = true;
    }
    for (const step of schedule.steps) {
      elements.scheduleStations.querySelector(`[data-station-id='${step.station_id}']`).checked = true;
      elements.scheduleStations.querySelector(`[data-duration-for='${step.station_id}']`).value = step.duration_seconds / 60;
    }
  }
  elements.scheduleDialog.showModal();
}

document.querySelector("#add-schedule-button").addEventListener("click", () => openScheduleDialog());

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
    const editing = state.editingScheduleId !== null;
    const existing = state.schedules.find((schedule) => schedule.id === state.editingScheduleId);
    await api(editing ? `/api/v1/schedules/${state.editingScheduleId}` : "/api/v1/schedules", {
      method: editing ? "PUT" : "POST",
      body: JSON.stringify({
        name: form.get("name"),
        enabled: existing?.enabled ?? true,
        start_time: form.get("start_time"),
        days_of_week: days,
        steps,
      }),
    });
    elements.scheduleDialog.close();
    await refreshSchedules();
    notify(editing ? "Schedule updated" : "Schedule created");
  } catch (error) {
    elements.scheduleError.textContent = error.message;
  }
});

refreshAll();
