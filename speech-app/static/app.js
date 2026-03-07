const recordButton = document.getElementById("recordButton");
const stopButton = document.getElementById("stopButton");
const status = document.getElementById("status");
const transcript = document.getElementById("transcript");
const providerSelect = document.getElementById("providerSelect");
const historyList = document.getElementById("historyList");
const robotHostInput = document.getElementById("robotHostInput");
const robotPortInput = document.getElementById("robotPortInput");
const robotPairingCodeInput = document.getElementById("robotPairingCodeInput");
const robotClientNameInput = document.getElementById("robotClientNameInput");
const discoverRobotsButton = document.getElementById("discoverRobotsButton");
const pairRobotButton = document.getElementById("pairRobotButton");
const refreshRobotButton = document.getElementById("refreshRobotButton");
const unpairRobotButton = document.getElementById("unpairRobotButton");
const sendTranscriptButton = document.getElementById("sendTranscriptButton");
const robotConnection = document.getElementById("robotConnection");
const robotStatus = document.getElementById("robotStatus");
const robotMeta = document.getElementById("robotMeta");
const discoveredRobots = document.getElementById("discoveredRobots");

const brailleSelect = document.getElementById("brailleSelect");
const transcriptFontTrigger = document.getElementById("transcriptFontTrigger");
const transcriptSizePicker = document.getElementById("transcriptSizePicker");
const fontPickerPanel = document.getElementById("fontPickerPanel");
const fontPickerSearch = document.getElementById("fontPickerSearch");
const fontPickerList = document.getElementById("fontPickerList");

const previewModal = document.getElementById("previewModal");
const previewModalClose = document.getElementById("previewModalClose");
const previewCanvas = document.getElementById("previewCanvas");
const previewPaperSize = document.getElementById("previewPaperSize");
const customPaperFields = document.getElementById("customPaperFields");
const previewPaperWidth = document.getElementById("previewPaperWidth");
const previewPaperHeight = document.getElementById("previewPaperHeight");
const previewRenderMode = document.getElementById("previewRenderMode");
const previewFontSize = document.getElementById("previewFontSize");
const previewPenTip = document.getElementById("previewPenTip");
const previewMarginTop = document.getElementById("previewMarginTop");
const previewMarginRight = document.getElementById("previewMarginRight");
const previewMarginBottom = document.getElementById("previewMarginBottom");
const previewMarginLeft = document.getElementById("previewMarginLeft");
const previewOffsetX = document.getElementById("previewOffsetX");
const previewOffsetY = document.getElementById("previewOffsetY");
const previewFontTrigger = document.getElementById("previewFontTrigger");
const previewFontValue = document.getElementById("previewFontValue");
const previewStats = document.getElementById("previewStats");
const previewPlayPause = document.getElementById("previewPlayPause");
const previewRestart = document.getElementById("previewRestart");
const previewSkip = document.getElementById("previewSkip");
const previewSpeed = document.getElementById("previewSpeed");

const DEFAULT_TRANSCRIPT_TEXT = "Your text will appear here.";
const HISTORY_STORAGE_KEY = "speechAppTranscriptHistory";
const HISTORY_LIMIT = 12;
const FONT_SIZES = [14, 16, 18, 20, 24, 28, 32, 40];
const DEFAULT_FONT_SIZE = 20;
const DEFAULT_FONT_FAMILY = "Noto Sans";
const DEFAULT_ROBOT_PORT = 8080;
const TRANSPORT_SERIAL = "serial";

let mediaRecorder;
let audioChunks = [];
let recordedMimeType = "audio/webm";
let currentTranscriptId = null;
let transcriptHistory = [];
let pairedRobot = null;
let robotConnected = false;
let activeRobotAction = null;
const fontCache = {};
let braillePreviewActive = false;

function brailleActive() { return brailleSelect.value !== "off"; }
function brailleGrade() { return Number(brailleSelect.value); }

async function updateBrailleGradeOptions(language) {
  try {
    const data = await fetchJson(`/braille/grades?language=${encodeURIComponent(language || "en")}`);
    const grades = data.grades || [];
    for (const opt of brailleSelect.options) {
      if (opt.value === "off") continue;
      opt.disabled = !grades.includes(Number(opt.value));
    }
    // If current selection is now disabled, fall back to "off"
    if (brailleSelect.selectedOptions[0]?.disabled) {
      brailleSelect.value = "off";
      restoreBraillePreview();
    }
  } catch {
    // On error, keep all options enabled
    for (const opt of brailleSelect.options) opt.disabled = false;
  }
}
let activeFontPicker = null; // { triggerEl, subset, currentFamily, onSelect }
let robotPollTimer = null;
let robotStateRequestInFlight = false;
let robotStateMutationVersion = 0;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function fetchBraillePreview(text, language, grade) {
  const data = await fetchJson("/braille/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language, grade }),
  });
  return data.braille_text || "";
}

async function applyBraillePreview() {
  if (!brailleActive()) {
    restoreBraillePreview();
    return;
  }

  const current = getCurrentTranscript();
  const text = current ? current.text : DEFAULT_TRANSCRIPT_TEXT;
  const language = current ? current.language : "en";
  const snapshotId = currentTranscriptId;

  try {
    const brailleText = await fetchBraillePreview(
      text,
      language,
      brailleGrade(),
    );
    // Re-check state hasn't changed during the async call
    if (!brailleActive() || currentTranscriptId !== snapshotId) return;
    transcript.textContent = brailleText;
    transcript.style.fontFamily = "";
    braillePreviewActive = true;
  } catch {
    // Silently fall back to original text
  }
}

function restoreBraillePreview() {
  if (!braillePreviewActive) return;
  braillePreviewActive = false;
  const current = getCurrentTranscript();
  if (current) {
    transcript.textContent = current.text;
    transcript.style.fontFamily = cssFontFamily(current.font_family);
  } else {
    transcript.textContent = DEFAULT_TRANSCRIPT_TEXT;
    transcript.style.fontFamily = "";
  }
}

const loadedFonts = new Set();

function ensureFont(family, url) {
  if (!url || loadedFonts.has(family)) return;
  loadedFonts.add(family);
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = url;
  document.head.appendChild(link);
}

function cssFontFamily(family) {
  return `"${family}", sans-serif`;
}

function buildGoogleFontsUrl(family) {
  return `https://fonts.googleapis.com/css2?family=${encodeURIComponent(family)}:wght@400;500;700&display=swap`;
}

async function getFontsForSubset(subset) {
  if (fontCache[subset]) return fontCache[subset];
  try {
    const data = await fetchJson(`/fonts?subset=${encodeURIComponent(subset)}`);
    fontCache[subset] = data.fonts || [];
  } catch {
    fontCache[subset] = [];
  }
  return fontCache[subset];
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  let payload = {};

  try {
    payload = await response.json();
  } catch {
    if (!response.ok) {
      throw new Error("Request failed.");
    }
    return {};
  }

  if (!response.ok) {
    throw new Error(payload.error || "Request failed.");
  }

  return payload;
}

function currentRobotPort() {
  const port = Number(robotPortInput.value || DEFAULT_ROBOT_PORT);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return DEFAULT_ROBOT_PORT;
  }
  return port;
}

function historyItemId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function normalizeHistoryItem(item) {
  if (!item || typeof item !== "object") {
    return null;
  }

  const text = typeof item.text === "string" ? item.text.trim() : "";
  if (!text) {
    return null;
  }

  const fs = Number(item.font_size);
  const ag = Array.isArray(item.available_grades) ? item.available_grades : [];
  const bg = item.braille_grade;
  return {
    id: typeof item.id === "string" && item.id ? item.id : historyItemId(),
    text,
    script: typeof item.script === "string" && item.script ? item.script : "latin",
    font_family: typeof item.font_family === "string" && item.font_family ? item.font_family : DEFAULT_FONT_FAMILY,
    font_url: typeof item.font_url === "string" ? item.font_url : "",
    font_size: FONT_SIZES.includes(fs) ? fs : DEFAULT_FONT_SIZE,
    provider: typeof item.provider === "string" && item.provider ? item.provider : "unknown",
    language: typeof item.language === "string" ? item.language : "",
    language_confidence: item.language_confidence ?? null,
    created_at: typeof item.created_at === "string" && item.created_at ? item.created_at : new Date().toISOString(),
    available_grades: ag,
    braille_grade: bg === "off" || bg === 1 || bg === 2 ? bg : "off",
  };
}

function loadTranscriptHistory() {
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const items = JSON.parse(raw);
    if (!Array.isArray(items)) {
      return [];
    }

    return items.map(normalizeHistoryItem).filter(Boolean).slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function persistTranscriptHistory() {
  try {
    window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(transcriptHistory.slice(0, HISTORY_LIMIT)));
  } catch {
    status.textContent = "Unable to save transcript history in this browser.";
  }
}

function updateHistoryActionButtons() {
  const disableSend = activeRobotAction !== null || !pairedRobot || !robotConnected;
  historyList.querySelectorAll(".history-send-button").forEach((button) => {
    button.disabled = disableSend;
  });
}

function closeFontPicker() {
  fontPickerPanel.classList.remove("open");
  activeFontPicker = null;
}

function renderFontList(fonts, selectedFamily, { hersheyFonts = [] } = {}) {
  let html = "";

  // Hershey fonts section (if provided)
  if (hersheyFonts.length) {
    html += '<div class="font-picker-group-label">Single-stroke (Hershey)</div>';
    html += hersheyFonts
      .map(
        (name) =>
          `<div class="font-picker-item${name === selectedFamily ? " selected" : ""}" data-family="${escapeHtml(name)}" data-hershey="1">${escapeHtml(name)}</div>`
      )
      .join("");
    if (fonts.length) {
      html += '<div class="font-picker-group-label">Google Fonts</div>';
    }
  }

  if (!fonts.length && !hersheyFonts.length) {
    fontPickerList.innerHTML = '<div class="font-picker-empty">No fonts found</div>';
    return;
  }

  html += fonts
    .map(
      (f) =>
        `<div class="font-picker-item${f.family === selectedFamily ? " selected" : ""}" data-family="${escapeHtml(f.family)}">${escapeHtml(f.family)}</div>`
    )
    .join("");

  fontPickerList.innerHTML = html;
}

async function openFontPicker(triggerEl, subset, currentFamily, onSelect, { hersheyFonts = [] } = {}) {
  if (activeFontPicker && activeFontPicker.triggerEl === triggerEl) {
    closeFontPicker();
    return;
  }

  activeFontPicker = { triggerEl, subset, currentFamily, onSelect, hersheyFonts };
  fontPickerSearch.value = "";
  fontPickerList.innerHTML = '<div class="font-picker-empty">Loading...</div>';
  fontPickerPanel.classList.add("open");

  // Position near the trigger. Use fixed positioning inside modals so
  // the picker doesn't scroll away; absolute everywhere else.
  const inModal = !!triggerEl.closest(".modal-overlay");
  const rect = triggerEl.getBoundingClientRect();
  if (inModal) {
    fontPickerPanel.style.position = "fixed";
    fontPickerPanel.style.top = (rect.bottom + 4) + "px";
    fontPickerPanel.style.left = rect.left + "px";
  } else {
    fontPickerPanel.style.position = "absolute";
    fontPickerPanel.style.top = (rect.bottom + window.scrollY + 4) + "px";
    fontPickerPanel.style.left = rect.left + "px";
  }

  fontPickerSearch.focus();

  const cached = await getFontsForSubset(subset);
  const fonts = [...cached];
  // Ensure current font is in the list without mutating cache
  // (skip for Hershey fonts — they appear in their own section)
  if (currentFamily && !hersheyFonts.includes(currentFamily) && !fonts.some((f) => f.family === currentFamily)) {
    fonts.unshift({ family: currentFamily, category: "" });
  }
  activeFontPicker.allFonts = fonts;
  renderFontList(fonts, currentFamily, { hersheyFonts });
}

function filterFontList() {
  if (!activeFontPicker?.allFonts) return;
  const q = fontPickerSearch.value.toLowerCase();
  const filtered = q
    ? activeFontPicker.allFonts.filter((f) => f.family.toLowerCase().includes(q))
    : activeFontPicker.allFonts;
  const hershey = activeFontPicker.hersheyFonts || [];
  const filteredHershey = q
    ? hershey.filter((name) => name.toLowerCase().includes(q))
    : hershey;
  renderFontList(filtered, activeFontPicker.currentFamily, { hersheyFonts: filteredHershey });
}

fontPickerSearch.addEventListener("input", filterFontList);

fontPickerList.addEventListener("click", (e) => {
  const item = e.target.closest(".font-picker-item");
  if (!item || !activeFontPicker) return;
  const family = item.dataset.family;
  activeFontPicker.currentFamily = family;
  activeFontPicker.onSelect(family);
  // Update trigger label
  const label = activeFontPicker.triggerEl.querySelector(".font-trigger-label");
  if (label) label.textContent = family;
  closeFontPicker();
});

document.addEventListener("mousedown", (e) => {
  if (!activeFontPicker) return;
  if (!fontPickerPanel.contains(e.target) && !activeFontPicker.triggerEl.contains(e.target)) {
    closeFontPicker();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && activeFontPicker) closeFontPicker();
});

function updateHistoryItem(id, updates) {
  const idx = transcriptHistory.findIndex((item) => item.id === id);
  if (idx === -1) return;
  transcriptHistory[idx] = { ...transcriptHistory[idx], ...updates };
  persistTranscriptHistory();
}

function setCurrentTranscript(item) {
  ensureFont(item.font_family, item.font_url);
  currentTranscriptId = item.id;
  braillePreviewActive = false;
  transcript.textContent = item.text;
  transcript.style.fontFamily = cssFontFamily(item.font_family);
  transcript.style.fontSize = item.font_size + "px";

  transcriptFontTrigger.dataset.subset = item.script;
  transcriptFontTrigger.querySelector(".font-trigger-label").textContent = item.font_family;
  transcriptSizePicker.value = String(item.font_size);
  syncRobotControls();
  updateBrailleGradeOptions(item.language);

  if (brailleActive()) applyBraillePreview();
}

function applyFontChange(id, family) {
  const url = buildGoogleFontsUrl(family);
  ensureFont(family, url);
  const textEl = historyList.querySelector(`[data-history-text-id="${id}"]`);
  if (textEl) textEl.style.fontFamily = cssFontFamily(family);
  const historyTrigger = historyList.querySelector(`.font-trigger[data-history-id="${id}"] .font-trigger-label`);
  if (historyTrigger) historyTrigger.textContent = family;
  if (currentTranscriptId === id) {
    transcript.style.fontFamily = cssFontFamily(family);
    transcriptFontTrigger.querySelector(".font-trigger-label").textContent = family;
  }
  updateHistoryItem(id, { font_family: family, font_url: url });
}

function clearCurrentTranscript() {
  currentTranscriptId = null;
  braillePreviewActive = false;
  transcript.textContent = DEFAULT_TRANSCRIPT_TEXT;
  transcript.style.fontFamily = "";
  transcript.style.fontSize = "";
  transcriptFontTrigger.dataset.subset = "latin";
  transcriptFontTrigger.querySelector(".font-trigger-label").textContent = "Font";
  transcriptSizePicker.value = String(DEFAULT_FONT_SIZE);
  syncRobotControls();

  if (brailleActive()) applyBraillePreview();
}

function addTranscriptToHistory(item) {
  const historyItem = normalizeHistoryItem({ ...item, id: historyItemId() });
  if (!historyItem) {
    return null;
  }

  transcriptHistory = [historyItem, ...transcriptHistory].slice(0, HISTORY_LIMIT);
  persistTranscriptHistory();
  renderHistory(transcriptHistory);
  return historyItem;
}

function deleteTranscriptFromHistory(id) {
  if (currentTranscriptId === id) {
    clearCurrentTranscript();
  }

  transcriptHistory = transcriptHistory.filter((item) => item.id !== id);
  persistTranscriptHistory();
  renderHistory(transcriptHistory);
}

function findTranscriptInHistory(id) {
  return transcriptHistory.find((item) => item.id === id) || null;
}

function getCurrentTranscript() {
  return currentTranscriptId ? findTranscriptInHistory(currentTranscriptId) : null;
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = "<p>No transcripts yet.</p>";
    return;
  }

  const disableSend = activeRobotAction !== null || !pairedRobot || !robotConnected;
  historyList.innerHTML = items
    .map(
      (i) => `<div class="history-item" data-history-id="${escapeHtml(i.id)}">
        <div class="history-copy">
          <small>${escapeHtml(i.provider)} &middot; ${escapeHtml(i.language || i.script)} &middot; ${escapeHtml(new Date(i.created_at).toLocaleString())}</small>
          <p style="font-family:${cssFontFamily(escapeHtml(i.font_family))};font-size:${i.font_size}px" data-history-text-id="${escapeHtml(i.id)}">${escapeHtml(i.text)}</p>
          <div class="history-style-controls">
            <select class="size-picker" data-history-id="${escapeHtml(i.id)}">
              ${FONT_SIZES.map((s) => `<option value="${s}"${s === i.font_size ? " selected" : ""}>${s}</option>`).join("")}
            </select>
            <button type="button" class="font-trigger" data-history-id="${escapeHtml(i.id)}" data-subset="${escapeHtml(i.script)}">
              <span class="font-trigger-label">${escapeHtml(i.font_family)}</span>
              <span class="font-trigger-arrow">&#9662;</span>
            </button>
            <select class="braille-picker" data-history-id="${escapeHtml(i.id)}">
              <option value="off"${i.braille_grade === "off" ? " selected" : ""}>Braille Off</option>
              ${!(i.available_grades || []).length || (i.available_grades || []).includes(1) ? `<option value="1"${i.braille_grade === 1 ? " selected" : ""}>Grade 1</option>` : ""}
              ${!(i.available_grades || []).length || (i.available_grades || []).includes(2) ? `<option value="2"${i.braille_grade === 2 ? " selected" : ""}>Grade 2</option>` : ""}
            </select>
          </div>
        </div>
        <div class="history-actions">
          <button type="button" class="history-send-button" data-history-id="${escapeHtml(i.id)}" ${disableSend ? "disabled" : ""}>Send to Robot</button>
          <button type="button" class="history-delete-button" data-history-id="${escapeHtml(i.id)}">Delete</button>
        </div>
      </div>`
    )
    .join("");

  updateHistoryActionButtons();
}

function syncRobotControls() {
  const robotBusy = activeRobotAction !== null;
  const canPair = !robotBusy;
  const canRefresh = !robotBusy;
  const canUnpair = !robotBusy && Boolean(pairedRobot);
  const canSendTranscript = !robotBusy && Boolean(pairedRobot) && robotConnected && currentTranscriptId !== null;

  discoverRobotsButton.disabled = robotBusy;
  pairRobotButton.disabled = !canPair;
  refreshRobotButton.disabled = !canRefresh;
  unpairRobotButton.disabled = !canUnpair;
  sendTranscriptButton.disabled = !canSendTranscript;
  updateHistoryActionButtons();
}

function markRobotStateMutation() {
  robotStateMutationVersion += 1;
}

function stopRobotPolling() {
  if (robotPollTimer !== null) {
    window.clearTimeout(robotPollTimer);
    robotPollTimer = null;
  }
}

function scheduleRobotPoll() {
  stopRobotPolling();
  if (!pairedRobot || document.hidden) {
    return;
  }

  robotPollTimer = window.setTimeout(() => {
    loadRobotState({ silent: true, passive: true });
  }, 8000);
}

function renderRobotState(payload, options = {}) {
  const { preserveStatus = false } = options;
  pairedRobot = payload.paired ? payload.robot : null;
  robotConnected = Boolean(payload.paired && payload.robot && payload.connected);

  if (!payload.paired || !payload.robot) {
    robotConnection.textContent = "No robot paired.";
    if (payload.warning) {
      robotStatus.textContent = payload.warning;
    } else if (!preserveStatus) {
      robotStatus.textContent = "Pair the speech app to your Pico 2 W over the current local network.";
    }
    robotMeta.innerHTML = "";
    syncRobotControls();
    stopRobotPolling();
    return;
  }

  robotHostInput.value = payload.robot.host;
  robotPortInput.value = payload.robot.port;
  robotClientNameInput.value = payload.robot.client_name;
  robotConnection.textContent = payload.connected ? "Robot connected." : "Robot paired, but currently unreachable.";
  if (!preserveStatus) {
    robotStatus.textContent = payload.error || (payload.status ? "Robot status is live." : "Robot is paired.");
  }
  const endpointLabel = payload.robot.transport === TRANSPORT_SERIAL
    ? `USB (${escapeHtml(payload.robot.serial_port || payload.robot.host)})`
    : escapeHtml(payload.robot.base_url);
  robotMeta.innerHTML = `
    <div class="meta-row"><strong>Device:</strong> ${escapeHtml(payload.robot.device_name)}</div>
    <div class="meta-row"><strong>ID:</strong> ${escapeHtml(payload.robot.device_id)}</div>
    <div class="meta-row"><strong>Endpoint:</strong> ${endpointLabel}</div>
    <div class="meta-row"><strong>Paired:</strong> ${escapeHtml(new Date(payload.robot.paired_at).toLocaleString())}</div>
  `;
  syncRobotControls();
  scheduleRobotPoll();
}

function renderDiscoveredRobots(items) {
  if (!items.length) {
    discoveredRobots.innerHTML = "<p>No robots discovered yet.</p>";
    return;
  }

  discoveredRobots.innerHTML = items
    .map(
      (item) => {
        const isUsb = Boolean(item.usb);
        const cssClass = isUsb ? "discovered-item discovered-usb" : "discovered-item";
        const address = isUsb ? escapeHtml(item.serial_port || item.host) : `${escapeHtml(item.host)}:${escapeHtml(String(item.port))}`;
        const buttonLabel = isUsb ? "Connect (USB)" : "Use This Robot";
        return `
        <div class="${cssClass}">
          <div class="discovered-copy">
            <strong>${escapeHtml(item.device_name)}</strong>
            <span>${address}</span>
          </div>
          <button
            type="button"
            class="use-robot-button"
            data-robot-host="${escapeHtml(item.host)}"
            data-robot-port="${escapeHtml(String(item.port))}"
            data-robot-name="${escapeHtml(item.device_name)}"
            data-robot-usb="${isUsb ? "1" : "0"}"
            data-robot-serial-port="${escapeHtml(item.serial_port || "")}"
          >
            ${buttonLabel}
          </button>
        </div>
      `;
      }
    )
    .join("");
}

async function loadRobotState(options = {}) {
  const { silent = false, passive = false } = options;
  if (robotStateRequestInFlight) {
    return;
  }

  const mutationVersion = robotStateMutationVersion;
  robotStateRequestInFlight = true;
  if (!passive) {
    syncRobotControls();
  }
  try {
    const payload = await fetchJson("/robot");
    if (mutationVersion !== robotStateMutationVersion) {
      return;
    }
    renderRobotState(payload, { preserveStatus: silent });
  } catch (error) {
    if (mutationVersion !== robotStateMutationVersion) {
      return;
    }
    robotConnection.textContent = "Robot status unavailable.";
    robotConnected = false;
    if (!silent) {
      robotStatus.textContent = error.message || "Unable to load robot state.";
    }
    if (!passive) {
      syncRobotControls();
    }
  } finally {
    robotStateRequestInFlight = false;
    if (!passive) {
      syncRobotControls();
    }
    if (pairedRobot) {
      scheduleRobotPoll();
    }
  }
}

function loadHistory() {
  transcriptHistory = loadTranscriptHistory();
  transcriptHistory.forEach((item) => ensureFont(item.font_family, item.font_url));
  renderHistory(transcriptHistory);
}

async function discoverRobots() {
  robotStatus.textContent = "Scanning the current local network for Pico robots...";
  activeRobotAction = "discover";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: currentRobotPort() }),
    });

    renderDiscoveredRobots(payload.items);
    robotStatus.textContent = payload.items.length
      ? "Discovery complete. Pick a robot and pair it."
      : "No robots replied. Check that the Pico joined the same local network.";
  } catch (error) {
    robotStatus.textContent = error.message || "Robot discovery failed.";
  } finally {
    activeRobotAction = null;
    syncRobotControls();
  }
}

async function doPairRequest(body, { pendingMsg, successMsg, failMsg }) {
  robotStatus.textContent = pendingMsg;
  markRobotStateMutation();
  activeRobotAction = "pair";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    renderRobotState(payload);
    robotStatus.textContent = payload.connected ? successMsg : (payload.error || failMsg);
    return payload;
  } catch (error) {
    robotStatus.textContent = error.message || failMsg;
    return null;
  } finally {
    activeRobotAction = null;
    syncRobotControls();
  }
}

async function pairRobot() {
  const payload = await doPairRequest(
    {
      host: robotHostInput.value,
      port: Number(robotPortInput.value || DEFAULT_ROBOT_PORT),
      pairing_code: robotPairingCodeInput.value,
      client_name: robotClientNameInput.value,
    },
    {
      pendingMsg: "Pairing with robot...",
      successMsg: "Pairing complete.",
      failMsg: "Pairing saved, but the robot is currently unreachable.",
    },
  );
  if (payload) {
    robotPairingCodeInput.value = "";
  }
}

async function unpairRobot() {
  robotStatus.textContent = "Removing robot pairing...";
  markRobotStateMutation();
  activeRobotAction = "unpair";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/unpair", { method: "POST" });
    renderRobotState(payload);
    robotStatus.textContent = payload.warning || "Robot unpaired.";
  } catch (error) {
    robotStatus.textContent = error.message || "Unpair failed.";
  } finally {
    activeRobotAction = null;
    syncRobotControls();
  }
}

async function sendTranscriptPayloadToRobot(transcriptToSend) {
  if (!transcriptToSend) {
    robotStatus.textContent = "Record and transcribe something first.";
    return;
  }
  if (!pairedRobot || !robotConnected) {
    robotStatus.textContent = "Pair with a reachable robot first.";
    return;
  }

  const isBraille = itemBrailleActive(transcriptToSend);
  robotStatus.textContent = isBraille
    ? "Sending Braille to robot..."
    : "Sending transcript to robot...";
  activeRobotAction = "render";
  syncRobotControls();

  try {
    const renderBody = isBraille
      ? {
          mode: "braille",
          text: transcriptToSend.text,
          language: transcriptToSend.language,
          grade: Number(transcriptToSend.braille_grade),
        }
      : {
          mode: "write",
          text: transcriptToSend.text,
          font_family: transcriptToSend.font_family,
          script: transcriptToSend.script,
        };

    const payload = await fetchJson("/robot/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(renderBody),
    });

    robotStatus.textContent = isBraille
      ? `Robot accepted Braille job ${payload.job_id}.`
      : `Robot accepted job ${payload.job_id}.`;
  } catch (error) {
    robotStatus.textContent = error.message || "Unable to send transcript.";
  } finally {
    activeRobotAction = null;
    syncRobotControls();
  }
}

async function sendTranscriptToRobot() {
  await sendTranscriptPayloadToRobot(getCurrentTranscript());
}

function ext(mime) {
  if (mime.includes("mp4")) return "mp4";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mpeg")) return "mp3";
  if (mime.includes("wav")) return "wav";
  return "webm";
}

async function upload() {
  const blob = new Blob(audioChunks, { type: recordedMimeType });
  const fd = new FormData();
  fd.append("audio", blob, `speech.${ext(recordedMimeType)}`);
  fd.append("provider", providerSelect.value);

  status.textContent = "Transcribing...";
  try {
    const data = await fetchJson("/transcribe", { method: "POST", body: fd });
    const historyItem = addTranscriptToHistory(data);
    if (!historyItem) {
      throw new Error("Transcription returned invalid data.");
    }
    setCurrentTranscript(historyItem);
    status.textContent = "Done.";
  } catch (e) {
    transcript.textContent = "Transcription failed.";
    status.textContent = e.message;
    currentTranscriptId = null;
    syncRobotControls();
  } finally {
    recordButton.disabled = false;
    providerSelect.disabled = false;
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    recordedMimeType = mediaRecorder.mimeType || "audio/webm";
    audioChunks = [];

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      upload();
    };

    mediaRecorder.start();
    recordButton.disabled = true;
    stopButton.disabled = false;
    providerSelect.disabled = true;
    status.textContent = "Recording...";
  } catch (e) {
    status.textContent = `Mic error: ${e.message}`;
  }
}

function stopRecording() {
  if (mediaRecorder?.state === "recording") {
    mediaRecorder.stop();
    stopButton.disabled = true;
    status.textContent = "Processing...";
  }
}

historyList.addEventListener("click", (event) => {
  const sendButton = event.target.closest(".history-send-button");
  if (sendButton) {
    const historyItem = findTranscriptInHistory(sendButton.dataset.historyId || "");
    if (historyItem) handleSendToRobot(historyItem);
    return;
  }

  const deleteButton = event.target.closest(".history-delete-button");
  if (deleteButton) {
    deleteTranscriptFromHistory(deleteButton.dataset.historyId || "");
    return;
  }

  // Braille picker is handled in the "change" listener below


  const trigger = event.target.closest(".font-trigger[data-history-id]");
  if (trigger) {
    const id = trigger.dataset.historyId || "";
    const item = findTranscriptInHistory(id);
    if (!item) return;
    openFontPicker(trigger, item.script, item.font_family, (family) => {
      applyFontChange(id, family);
    });
  }
});

historyList.addEventListener("change", (event) => {
  const picker = event.target.closest(".size-picker[data-history-id]");
  if (picker) {
    const id = picker.dataset.historyId || "";
    const size = Number(picker.value);
    const textEl = historyList.querySelector(`[data-history-text-id="${id}"]`);
    if (textEl) textEl.style.fontSize = size + "px";
    if (currentTranscriptId === id) {
      transcript.style.fontSize = size + "px";
      transcriptSizePicker.value = String(size);
    }
    updateHistoryItem(id, { font_size: size });
    return;
  }

  const braillePicker = event.target.closest(".braille-picker[data-history-id]");
  if (braillePicker) {
    const id = braillePicker.dataset.historyId || "";
    const item = findTranscriptInHistory(id);
    if (!item) return;
    const textEl = historyList.querySelector(`[data-history-text-id="${id}"]`);
    if (!textEl) return;
    const val = braillePicker.value;
    const grade = val === "off" ? "off" : Number(val);
    updateHistoryItem(id, { braille_grade: grade });

    if (grade === "off") {
      textEl.textContent = item.text;
      textEl.style.fontFamily = cssFontFamily(item.font_family);
    } else {
      braillePicker.disabled = true;
      fetchBraillePreview(item.text, item.language, grade)
        .then((brailleText) => {
          textEl.textContent = brailleText;
          textEl.style.fontFamily = "";
        })
        .catch(() => {})
        .finally(() => { braillePicker.disabled = false; });
    }

    // Sync the top-level braille selector if this is the current transcript
    if (currentTranscriptId === id) {
      brailleSelect.value = String(grade === "off" ? "off" : grade);
      if (grade === "off") {
        restoreBraillePreview();
      } else {
        applyBraillePreview();
      }
    }
    return;
  }
});

transcriptSizePicker.addEventListener("change", () => {
  const size = Number(transcriptSizePicker.value);
  transcript.style.fontSize = size + "px";
  if (currentTranscriptId) {
    const textEl = historyList.querySelector(`[data-history-text-id="${currentTranscriptId}"]`);
    if (textEl) textEl.style.fontSize = size + "px";
    const historyPicker = historyList.querySelector(`.size-picker[data-history-id="${currentTranscriptId}"]`);
    if (historyPicker) historyPicker.value = String(size);
    updateHistoryItem(currentTranscriptId, { font_size: size });
  }
});

transcriptFontTrigger.addEventListener("click", () => {
  const subset = transcriptFontTrigger.dataset.subset || "latin";
  const current = getCurrentTranscript();
  const currentFamily = current?.font_family || "";
  openFontPicker(
    transcriptFontTrigger,
    subset,
    currentFamily,
    (family) => {
      if (currentTranscriptId) {
        applyFontChange(currentTranscriptId, family);
      } else {
        // Pre-apply font to transcript area for next recording
        const url = buildGoogleFontsUrl(family);
        ensureFont(family, url);
        transcript.style.fontFamily = cssFontFamily(family);
      }
    }
  );
});

discoveredRobots.addEventListener("click", async (event) => {
  const button = event.target.closest(".use-robot-button");
  if (!button) {
    return;
  }

  if (button.dataset.robotUsb === "1") {
    await doPairRequest(
      {
        transport: TRANSPORT_SERIAL,
        serial_port: button.dataset.robotSerialPort,
        client_name: robotClientNameInput.value || "speech-app",
      },
      {
        pendingMsg: "Connecting via USB...",
        successMsg: "USB robot connected.",
        failMsg: "USB pairing saved, but robot is unreachable.",
      },
    );
    return;
  }

  robotHostInput.value = button.dataset.robotHost || "";
  robotPortInput.value = button.dataset.robotPort || String(DEFAULT_ROBOT_PORT);
  robotStatus.textContent = `Loaded ${button.dataset.robotName || "robot"}. Enter the pairing code to complete pairing.`;
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopRobotPolling();
    return;
  }

  if (pairedRobot) {
    loadRobotState({ silent: true, passive: true });
  }
});

brailleSelect.addEventListener("change", () => {
  if (brailleActive()) {
    applyBraillePreview();
  } else {
    restoreBraillePreview();
  }
  // Sync to current transcript's history item and history braille picker
  if (currentTranscriptId) {
    const grade = brailleActive() ? brailleGrade() : "off";
    updateHistoryItem(currentTranscriptId, { braille_grade: grade });
    const historyBraille = historyList.querySelector(`.braille-picker[data-history-id="${currentTranscriptId}"]`);
    if (historyBraille) historyBraille.value = String(grade === "off" ? "off" : grade);
  }
});

// ── Preview Modal ──

let previewAnimationState = null;
let previewDebounceTimer = null;
let currentPreviewData = null;
let cachedPaperSizes = null;
let previewTranscriptItem = null;

let cachedHersheyFonts = null;

async function loadHersheyFonts() {
  if (cachedHersheyFonts) return cachedHersheyFonts;
  try {
    const data = await fetchJson("/hershey-fonts");
    cachedHersheyFonts = data.fonts || [];
  } catch {
    cachedHersheyFonts = [];
  }
  return cachedHersheyFonts;
}

function isHersheyFont(fontFamily) {
  return cachedHersheyFonts && cachedHersheyFonts.includes(fontFamily);
}

function updateRenderModeForFont() {
  const selected = previewFontValue.value;
  if (isHersheyFont(selected)) {
    previewRenderMode.disabled = true;
    previewRenderMode.value = "outline";
    previewRenderMode.title = "Hershey fonts are already single-stroke";
  } else {
    previewRenderMode.disabled = false;
    previewRenderMode.title = "";
  }
}

function setPreviewFont(family) {
  previewFontValue.value = family;
  const label = previewFontTrigger.querySelector(".font-trigger-label");
  if (label) label.textContent = family;
  updateRenderModeForFont();
  debouncedRefreshPreview();
}

async function loadPaperSizes() {
  if (cachedPaperSizes) return;
  try {
    const [paperData] = await Promise.all([
      fetchJson("/paper-sizes"),
      loadHersheyFonts(),
    ]);
    cachedPaperSizes = paperData;
    previewPaperSize.innerHTML = "";
    for (const size of paperData.sizes) {
      const opt = document.createElement("option");
      opt.value = size.name;
      opt.textContent = `${size.name} (${size.width} x ${size.height} mm)`;
      previewPaperSize.appendChild(opt);
    }
    const customOpt = document.createElement("option");
    customOpt.value = "Custom";
    customOpt.textContent = "Custom...";
    previewPaperSize.appendChild(customOpt);

    if (paperData.defaults) {
      previewFontSize.value = paperData.defaults.font_size_mm;
      previewPenTip.value = paperData.defaults.pen_tip_mm;
      previewMarginTop.value = paperData.defaults.margins.top;
      previewMarginRight.value = paperData.defaults.margins.right;
      previewMarginBottom.value = paperData.defaults.margins.bottom;
      previewMarginLeft.value = paperData.defaults.margins.left;
      previewOffsetX.value = paperData.defaults.paper_offset.x;
      previewOffsetY.value = paperData.defaults.paper_offset.y;
    }
  } catch {
    previewPaperSize.innerHTML = '<option value="A4">A4 (210 x 297 mm)</option>';
  }
}

function getPreviewParams(item) {
  const params = {
    text: item.text,
    paper_size: previewPaperSize.value,
    margins: {
      top: Number(previewMarginTop.value) || 10,
      right: Number(previewMarginRight.value) || 10,
      bottom: Number(previewMarginBottom.value) || 10,
      left: Number(previewMarginLeft.value) || 10,
    },
    paper_offset: {
      x: Number(previewOffsetX.value) || 0,
      y: Number(previewOffsetY.value) || 0,
    },
  };

  if (previewPaperSize.value === "Custom") {
    params.paper_width = Number(previewPaperWidth.value) || 210;
    params.paper_height = Number(previewPaperHeight.value) || 297;
  }

  if (itemBrailleActive(item)) {
    params.mode = "braille";
    params.language = item.language || "en";
    params.grade = Number(item.braille_grade);
  } else {
    params.mode = "write";
    params.font_family = previewFontValue.value || item.font_family;
    params.font_size_mm = Number(previewFontSize.value) || 5;
    params.pen_tip_mm = Number(previewPenTip.value) || 0.7;
    params.render_mode = previewRenderMode.value;
  }

  return params;
}

async function fetchPreview(item) {
  const params = getPreviewParams(item);
  previewStats.textContent = "Generating preview...";
  try {
    const data = await fetchJson("/toolpath/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    currentPreviewData = data;
    renderPreviewStats(data);
    startPreviewAnimation(data);
  } catch (err) {
    previewStats.textContent = err.message || "Preview failed.";
    currentPreviewData = null;
  }
}

function renderPreviewStats(data) {
  if (!data || !data.stats) {
    previewStats.textContent = "";
    return;
  }
  const s = data.stats;
  if (data.mode === "braille") {
    previewStats.textContent = `Punches: ${s.punch_count} | Travel: ${s.travel_distance_mm}mm`;
  } else {
    previewStats.textContent = `Paths: ${s.draw_count} | Draw: ${s.draw_distance_mm}mm | Travel: ${s.travel_distance_mm}mm`;
  }
}

// ── Animated Canvas Rendering ──

function startPreviewAnimation(data) {
  stopPreviewAnimation();

  const canvas = previewCanvas;
  const ctx = canvas.getContext("2d");
  const paper = data.paper;

  // Scale to fit canvas with padding
  const padding = 20;
  const scaleX = (canvas.width - 2 * padding) / paper.width;
  const scaleY = (canvas.height - 2 * padding) / paper.height;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = padding + (canvas.width - 2 * padding - paper.width * scale) / 2;
  const offsetY = padding + (canvas.height - 2 * padding - paper.height * scale) / 2;

  function toCanvas(x, y) {
    return [offsetX + x * scale, offsetY + y * scale];
  }

  // Flatten all operations into segments for animation
  const ops = data.operations || [];
  const segments = [];
  for (const op of ops) {
    if (op.type === "travel" || op.type === "draw") {
      const pts = op.points || [];
      let totalLen = 0;
      for (let i = 1; i < pts.length; i++) {
        totalLen += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      }
      segments.push({ type: op.type, points: pts, length: totalLen });
    } else if (op.type === "punch") {
      segments.push({ type: "punch", point: op.point, length: 0 });
    }
  }

  let totalLength = 0;
  for (const seg of segments) totalLength += Math.max(seg.length, 0.5);

  const penTipMm = data.pen_tip_mm || 0;
  const penTipPx = penTipMm * scale;

  const state = {
    segments,
    currentSegIndex: 0,
    currentSegProgress: 0,
    playing: true,
    speed: Number(previewSpeed.value) || 5,
    done: false,
    scale,
    offsetX,
    offsetY,
    paper,
    margins: data.margins || { top: 10, right: 10, bottom: 10, left: 10 },
    toCanvas,
    totalLength,
    penTipPx,
    // Track completed items for persistent rendering
    completedOps: [],
    toolheadPos: null,
    animFrameId: null,
    lastTime: null,
    pixelsPerMs: 0.15,  // base animation speed in mm/ms
  };

  previewAnimationState = state;
  previewPlayPause.textContent = "\u23F8";

  function animate(timestamp) {
    if (!state.playing || state.done) {
      state.animFrameId = null;
      return;
    }

    if (!state.lastTime) state.lastTime = timestamp;
    const dt = timestamp - state.lastTime;
    state.lastTime = timestamp;

    const advanceMm = state.pixelsPerMs * state.speed * dt;
    advanceAnimation(state, advanceMm);
    drawFrame(ctx, canvas, state);

    if (!state.done) {
      state.animFrameId = requestAnimationFrame(animate);
    }
  }

  drawFrame(ctx, canvas, state);
  state.animFrameId = requestAnimationFrame(animate);
}

function advanceAnimation(state, advanceMm) {
  let remaining = advanceMm;

  while (remaining > 0 && state.currentSegIndex < state.segments.length) {
    const seg = state.segments[state.currentSegIndex];

    if (seg.type === "punch") {
      state.completedOps.push({ ...seg });
      state.toolheadPos = seg.point;
      state.currentSegIndex++;
      state.currentSegProgress = 0;
      remaining -= 0.5;
      continue;
    }

    const segLen = seg.length || 0.01;
    const progressNeeded = segLen - state.currentSegProgress;

    if (remaining >= progressNeeded) {
      remaining -= progressNeeded;
      state.completedOps.push({
        type: seg.type,
        points: seg.points,
      });
      state.toolheadPos = seg.points[seg.points.length - 1];
      state.currentSegIndex++;
      state.currentSegProgress = 0;
    } else {
      state.currentSegProgress += remaining;
      // Find interpolated position
      state.toolheadPos = interpolateAlongPath(seg.points, state.currentSegProgress / segLen);
      remaining = 0;
    }
  }

  if (state.currentSegIndex >= state.segments.length) {
    state.done = true;
    previewPlayPause.textContent = "\u25B6";
  }
}

function interpolateAlongPath(points, fraction) {
  if (points.length < 2) return points[0] || [0, 0];
  fraction = Math.max(0, Math.min(1, fraction));

  let totalLen = 0;
  for (let i = 1; i < points.length; i++) {
    totalLen += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  }

  let target = fraction * totalLen;
  let accumulated = 0;

  for (let i = 1; i < points.length; i++) {
    const segLen = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    if (accumulated + segLen >= target) {
      const t = segLen > 0 ? (target - accumulated) / segLen : 0;
      return [
        points[i - 1][0] + t * (points[i][0] - points[i - 1][0]),
        points[i - 1][1] + t * (points[i][1] - points[i - 1][1]),
      ];
    }
    accumulated += segLen;
  }

  return points[points.length - 1];
}

function drawFrame(ctx, canvas, state) {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const { toCanvas, paper, margins } = state;

  // Draw paper
  const [px0, py0] = toCanvas(0, 0);
  const [px1, py1] = toCanvas(paper.width, paper.height);
  ctx.fillStyle = "white";
  ctx.fillRect(px0, py0, px1 - px0, py1 - py0);
  ctx.strokeStyle = "#999";
  ctx.lineWidth = 1;
  ctx.strokeRect(px0, py0, px1 - px0, py1 - py0);

  // Draw margin guides (dashed)
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#ccc";
  ctx.lineWidth = 0.5;
  const [mx0, my0] = toCanvas(margins.left, margins.top);
  const [mx1, my1] = toCanvas(paper.width - margins.right, paper.height - margins.bottom);
  ctx.strokeRect(mx0, my0, mx1 - mx0, my1 - my0);
  ctx.setLineDash([]);

  // --- Ink layer: shows expected pen output on paper ---
  if (state.penTipPx > 0.5) {
    for (const op of state.completedOps) {
      if (op.type === "draw") drawInkPath(ctx, state, op.points);
      else if (op.type === "punch") drawPunchPoint(ctx, state, op.point);
    }
    if (!state.done && state.currentSegIndex < state.segments.length) {
      const seg = state.segments[state.currentSegIndex];
      if (seg.type === "draw" && seg.length > 0) {
        const frac = state.currentSegProgress / seg.length;
        drawInkPath(ctx, state, getPartialPath(seg.points, frac));
      }
    }
  }

  // --- Toolpath layer: shows pen movement ---
  for (const op of state.completedOps) {
    if (op.type === "travel") {
      drawTravelPath(ctx, state, op.points);
    } else if (op.type === "draw") {
      drawDrawPath(ctx, state, op.points);
    } else if (op.type === "punch" && !(state.penTipPx > 0.5)) {
      drawPunchPoint(ctx, state, op.point);
    }
  }

  // Draw current in-progress segment
  if (!state.done && state.currentSegIndex < state.segments.length) {
    const seg = state.segments[state.currentSegIndex];
    if ((seg.type === "travel" || seg.type === "draw") && seg.length > 0) {
      const frac = state.currentSegProgress / seg.length;
      const partialPoints = getPartialPath(seg.points, frac);
      if (seg.type === "travel") {
        drawTravelPath(ctx, state, partialPoints);
      } else {
        drawDrawPath(ctx, state, partialPoints);
      }
    }
  }

  // Draw toolhead
  if (state.toolheadPos) {
    const [tx, ty] = toCanvas(state.toolheadPos[0], state.toolheadPos[1]);
    ctx.beginPath();
    ctx.arc(tx, ty, 4, 0, 2 * Math.PI);
    ctx.fillStyle = "#e53935";
    ctx.fill();
    ctx.strokeStyle = "white";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

function getPartialPath(points, fraction) {
  if (points.length < 2 || fraction <= 0) return [points[0]];
  if (fraction >= 1) return points;

  let totalLen = 0;
  for (let i = 1; i < points.length; i++) {
    totalLen += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  }

  const target = fraction * totalLen;
  let accumulated = 0;
  const result = [points[0]];

  for (let i = 1; i < points.length; i++) {
    const segLen = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
    if (accumulated + segLen >= target) {
      const t = segLen > 0 ? (target - accumulated) / segLen : 0;
      result.push([
        points[i - 1][0] + t * (points[i][0] - points[i - 1][0]),
        points[i - 1][1] + t * (points[i][1] - points[i - 1][1]),
      ]);
      return result;
    }
    accumulated += segLen;
    result.push(points[i]);
  }

  return result;
}

function drawTravelPath(ctx, state, points) {
  if (points.length < 2) return;
  ctx.beginPath();
  const [sx, sy] = state.toCanvas(points[0][0], points[0][1]);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < points.length; i++) {
    const [x, y] = state.toCanvas(points[i][0], points[i][1]);
    ctx.lineTo(x, y);
  }
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = "rgba(150, 150, 150, 0.4)";
  ctx.lineWidth = 0.5;
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawDrawPath(ctx, state, points) {
  if (points.length < 2) return;
  ctx.beginPath();
  const [sx, sy] = state.toCanvas(points[0][0], points[0][1]);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < points.length; i++) {
    const [x, y] = state.toCanvas(points[i][0], points[i][1]);
    ctx.lineTo(x, y);
  }
  // If ink layer is visible, draw toolpath as a subtle colored line
  if (state.penTipPx > 0.5) {
    ctx.strokeStyle = "rgba(220, 50, 50, 0.5)";
    ctx.lineWidth = 0.8;
  } else {
    ctx.strokeStyle = "#222";
    ctx.lineWidth = 1.2;
  }
  ctx.stroke();
}

function drawInkPath(ctx, state, points) {
  if (points.length < 2) return;
  ctx.beginPath();
  const [sx, sy] = state.toCanvas(points[0][0], points[0][1]);
  ctx.moveTo(sx, sy);
  for (let i = 1; i < points.length; i++) {
    const [x, y] = state.toCanvas(points[i][0], points[i][1]);
    ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "rgba(30, 30, 30, 0.25)";
  ctx.lineWidth = state.penTipPx;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke();
  ctx.lineCap = "butt";
  ctx.lineJoin = "miter";
}

function drawPunchPoint(ctx, state, point) {
  const [x, y] = state.toCanvas(point[0], point[1]);
  ctx.beginPath();
  ctx.arc(x, y, 3, 0, 2 * Math.PI);
  ctx.fillStyle = "#1a73e8";
  ctx.fill();
}

function stopPreviewAnimation() {
  if (previewAnimationState?.animFrameId) {
    cancelAnimationFrame(previewAnimationState.animFrameId);
  }
  previewAnimationState = null;
}

function skipPreviewAnimation() {
  if (!previewAnimationState || !currentPreviewData) return;
  stopPreviewAnimation();
  // Render final state instantly
  const canvas = previewCanvas;
  const ctx = canvas.getContext("2d");
  const data = currentPreviewData;
  const paper = data.paper;
  const padding = 20;
  const scaleX = (canvas.width - 2 * padding) / paper.width;
  const scaleY = (canvas.height - 2 * padding) / paper.height;
  const scale = Math.min(scaleX, scaleY);
  const oX = padding + (canvas.width - 2 * padding - paper.width * scale) / 2;
  const oY = padding + (canvas.height - 2 * padding - paper.height * scale) / 2;
  function toCanvas(x, y) { return [oX + x * scale, oY + y * scale]; }

  const penTipMm = data.pen_tip_mm || 0;
  const finalState = {
    toCanvas,
    paper,
    margins: data.margins || { top: 10, right: 10, bottom: 10, left: 10 },
    penTipPx: penTipMm * scale,
    completedOps: (data.operations || []).map((op) => ({ ...op })),
    done: true,
    toolheadPos: null,
    segments: [],
    currentSegIndex: 0,
    currentSegProgress: 0,
  };

  // Find last position
  const ops = data.operations || [];
  for (let i = ops.length - 1; i >= 0; i--) {
    if (ops[i].type === "punch") {
      finalState.toolheadPos = ops[i].point;
      break;
    }
    if (ops[i].type === "draw" || ops[i].type === "travel") {
      const pts = ops[i].points;
      finalState.toolheadPos = pts[pts.length - 1];
      break;
    }
  }

  previewAnimationState = finalState;
  drawFrame(ctx, canvas, finalState);
  previewPlayPause.textContent = "\u25B6";
}

function pxToMm(px) {
  // Convert CSS px to physical mm for robot writing.
  // At 96 DPI, 1px = 0.2646mm. We use 0.25 for a clean mapping:
  // 14px -> 3.5mm, 20px -> 5mm, 40px -> 10mm
  return Math.round(px * 0.25 * 2) / 2; // round to nearest 0.5
}

function itemBrailleActive(item) {
  return item.braille_grade !== "off" && item.braille_grade != null;
}

function openPreviewModal(item) {
  previewTranscriptItem = item;
  previewModal.style.display = "";

  const isBraille = itemBrailleActive(item);

  // Sync font size from transcript item
  if (item.font_size) {
    previewFontSize.value = pxToMm(item.font_size);
  }

  // Set up font trigger for modal
  const fontLabel = previewFontTrigger.closest("label");
  if (isBraille) {
    if (fontLabel) fontLabel.style.display = "none";
  } else {
    if (fontLabel) fontLabel.style.display = "";
    setPreviewFont(item.font_family);
    previewFontTrigger.dataset.subset = item.script || "latin";
  }

  // Hide render mode selector for braille
  const renderModeLabel = previewRenderMode.closest("label");
  const fontSizeLabel = previewFontSize.closest("label");
  const penTipLabel = previewPenTip.closest("label");
  if (isBraille) {
    if (renderModeLabel) renderModeLabel.style.display = "none";
    if (fontSizeLabel) fontSizeLabel.style.display = "none";
    if (penTipLabel) penTipLabel.style.display = "none";
  } else {
    if (renderModeLabel) renderModeLabel.style.display = "";
    if (fontSizeLabel) fontSizeLabel.style.display = "";
    if (penTipLabel) penTipLabel.style.display = "";
  }

  fetchPreview(item);
}

function closePreviewModal() {
  previewModal.style.display = "none";
  stopPreviewAnimation();
  currentPreviewData = null;
  previewTranscriptItem = null;
}

function debouncedRefreshPreview() {
  if (!previewTranscriptItem) return;
  clearTimeout(previewDebounceTimer);
  previewDebounceTimer = setTimeout(() => {
    fetchPreview(previewTranscriptItem);
  }, 300);
}

// Modal event listeners
previewModalClose.addEventListener("click", closePreviewModal);
previewModal.addEventListener("click", (e) => {
  if (e.target === previewModal) closePreviewModal();
});

previewPlayPause.addEventListener("click", () => {
  if (!previewAnimationState) return;
  if (previewAnimationState.done) {
    // Restart
    if (currentPreviewData) startPreviewAnimation(currentPreviewData);
    return;
  }
  previewAnimationState.playing = !previewAnimationState.playing;
  previewPlayPause.textContent = previewAnimationState.playing ? "\u23F8" : "\u25B6";
  if (previewAnimationState.playing) {
    previewAnimationState.lastTime = null;
    previewAnimationState.animFrameId = requestAnimationFrame(function animate(ts) {
      if (!previewAnimationState?.playing || previewAnimationState.done) return;
      if (!previewAnimationState.lastTime) previewAnimationState.lastTime = ts;
      const dt = ts - previewAnimationState.lastTime;
      previewAnimationState.lastTime = ts;
      advanceAnimation(previewAnimationState, previewAnimationState.pixelsPerMs * previewAnimationState.speed * dt);
      drawFrame(previewCanvas.getContext("2d"), previewCanvas, previewAnimationState);
      if (!previewAnimationState.done) {
        previewAnimationState.animFrameId = requestAnimationFrame(animate);
      } else {
        previewPlayPause.textContent = "\u25B6";
      }
    });
  }
});

previewRestart.addEventListener("click", () => {
  if (currentPreviewData) startPreviewAnimation(currentPreviewData);
});

previewSkip.addEventListener("click", skipPreviewAnimation);

previewSpeed.addEventListener("change", () => {
  if (previewAnimationState) {
    previewAnimationState.speed = Number(previewSpeed.value) || 5;
  }
});

previewPaperSize.addEventListener("change", () => {
  customPaperFields.style.display = previewPaperSize.value === "Custom" ? "" : "none";
  debouncedRefreshPreview();
});

// Parameter change listeners
for (const el of [
  previewPaperWidth, previewPaperHeight, previewRenderMode,
  previewFontSize, previewPenTip,
  previewMarginTop, previewMarginRight, previewMarginBottom, previewMarginLeft,
  previewOffsetX, previewOffsetY,
]) {
  el.addEventListener("change", debouncedRefreshPreview);
  el.addEventListener("input", debouncedRefreshPreview);
}

// Modal font picker trigger
previewFontTrigger.addEventListener("click", () => {
  const subset = previewFontTrigger.dataset.subset || "latin";
  const currentFamily = previewFontValue.value;
  openFontPicker(previewFontTrigger, subset, currentFamily, setPreviewFont, {
    hersheyFonts: cachedHersheyFonts || [],
  });
});

// ── Intercept Send-to-Robot clicks to open modal ──

function handleSendToRobot(item) {
  if (!item) {
    robotStatus.textContent = "Record and transcribe something first.";
    return;
  }
  openPreviewModal(item);
}

recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
pairRobotButton.addEventListener("click", pairRobot);
discoverRobotsButton.addEventListener("click", discoverRobots);
refreshRobotButton.addEventListener("click", loadRobotState);
unpairRobotButton.addEventListener("click", unpairRobot);
sendTranscriptButton.addEventListener("click", () => handleSendToRobot(getCurrentTranscript()));
transcriptSizePicker.innerHTML = FONT_SIZES.map(
  (s) => `<option value="${s}"${s === DEFAULT_FONT_SIZE ? " selected" : ""}>${s}</option>`
).join("");
loadHistory();
loadRobotState();
loadPaperSizes();
