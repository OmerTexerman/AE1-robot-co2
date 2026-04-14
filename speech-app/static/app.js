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
const previewSendButton = document.getElementById("previewSendButton");
const previewJobStatus = document.getElementById("previewJobStatus");

const homeRobotButton = document.getElementById("homeRobotButton");
const calibrateRobotButton = document.getElementById("calibrateRobotButton");
const abortRobotButton = document.getElementById("abortRobotButton");
const robotJobIndicator = document.getElementById("robotJobIndicator");
const penCalibrationPanel = document.getElementById("penCalibrationPanel");
const penServoSlider = document.getElementById("penServoSlider");
const penServoValue = document.getElementById("penServoValue");
const penSaveUpButton = document.getElementById("penSaveUpButton");
const penSaveDownButton = document.getElementById("penSaveDownButton");
const penSavePunchButton = document.getElementById("penSavePunchButton");
const penUpValue = document.getElementById("penUpValue");
const penDownValue = document.getElementById("penDownValue");
const penPunchValue = document.getElementById("penPunchValue");
const penCalibrationStatus = document.getElementById("penCalibrationStatus");
const penCalibrationMessage = document.getElementById("penCalibrationMessage");

const DEFAULT_TRANSCRIPT_TEXT = "Your text will appear here.";
const HISTORY_STORAGE_KEY = "speechAppTranscriptHistory";
const HISTORY_LIMIT = 12;
const FONT_SIZES = [14, 16, 18, 20, 24, 28, 32, 40];
const DEFAULT_FONT_SIZE = 20;
const DEFAULT_FONT_FAMILY = "Noto Sans";
const DEFAULT_ROBOT_PORT = 8080;
const DEFAULT_PEN_DUTY_MIN = 1600;
const DEFAULT_PEN_DUTY_MAX = 8000;
const TRANSPORT_SERIAL = "serial";
const DEFAULT_ROBOT_STATUS_TEXT = "Pair the speech app to your Pico over USB or the current local network.";
const NO_TRANSCRIPT_TEXT = "Record and transcribe something first.";
const UNREACHABLE_ROBOT_TEXT = "Pair with a reachable robot first.";
const PEN_CALIBRATION_DISABLED_TEXT = "Pen calibration is disabled while the robot is moving.";

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
    if (brailleSelect.selectedOptions[0]?.disabled) {
      brailleSelect.value = "off";
      restoreBraillePreview();
    }
  } catch {
    for (const opt of brailleSelect.options) opt.disabled = false;
  }
}
let activeFontPicker = null;
let robotPollTimer = null;
let robotStateRequestInFlight = false;
let robotStateMutationVersion = 0;
let robotJobPollTimer = null;
let robotJobInFlight = false;
let robotJobInPreviewMode = false;
let lastRobotJobStatus = null;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function setPenCalibrationMessage(message = "", isError = false) {
  if (!penCalibrationMessage) return;
  penCalibrationMessage.hidden = !message;
  penCalibrationMessage.textContent = message;
  penCalibrationMessage.style.color = isError ? "red" : "";
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
    if (!brailleActive() || currentTranscriptId !== snapshotId) return;
    updateStyledText(transcript, { text: brailleText, fontFamily: "" });
    braillePreviewActive = true;
  } catch {
  }
}

function restoreBraillePreview() {
  if (!braillePreviewActive) return;
  braillePreviewActive = false;
  const current = getCurrentTranscript();
  if (current) {
    updateStyledText(transcript, {
      text: current.text,
      fontFamily: current.font_family,
    });
  } else {
    updateStyledText(transcript, {
      text: DEFAULT_TRANSCRIPT_TEXT,
      fontFamily: "",
    });
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

function updateStyledText(element, { text, fontFamily, fontSize } = {}) {
  if (!element) return;
  if (text !== undefined) {
    element.textContent = text;
  }
  if (fontFamily !== undefined) {
    element.style.fontFamily = fontFamily ? cssFontFamily(fontFamily) : "";
  }
  if (fontSize !== undefined) {
    element.style.fontSize = fontSize === "" ? "" : `${fontSize}px`;
  }
}

function setElementDisplay(element, visible) {
  if (element) {
    element.style.display = visible ? "" : "none";
  }
}

function updateHistoryText(itemId, updates) {
  const textEl = historyList.querySelector(`[data-history-text-id="${itemId}"]`);
  updateStyledText(textEl, updates);
}

function restoreHistoryText(item) {
  updateHistoryText(item.id, { text: item.text, fontFamily: item.font_family });
}

function setHistoryBrailleText(item, brailleText) {
  updateHistoryItem(item.id, { braille_text: brailleText });
  updateHistoryText(item.id, { text: brailleText, fontFamily: "" });
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
  const bt = typeof item.braille_text === "string" ? item.braille_text : "";
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
    braille_text: bt,
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

function historyBrailleOptions(item) {
  const available = Array.isArray(item.available_grades) ? item.available_grades : [];
  const options = ['<option value="off">Braille Off</option>'];

  if (!available.length || available.includes(1)) {
    options.push(`<option value="1"${item.braille_grade === 1 ? " selected" : ""}>Grade 1</option>`);
  }

  if (!available.length || available.includes(2)) {
    options.push(`<option value="2"${item.braille_grade === 2 ? " selected" : ""}>Grade 2</option>`);
  }

  return options.join("");
}

function renderHistoryItem(item, disableSend) {
  const showBraille = item.braille_grade !== "off" && item.braille_text;
  const displayText = showBraille ? item.braille_text : item.text;
  const displayFont = showBraille ? "" : item.font_family;
  const textStyle = displayFont
    ? `font-family:${escapeHtml(cssFontFamily(displayFont))};font-size:${item.font_size}px`
    : `font-size:${item.font_size}px`;

  return `<div class="history-item" data-history-id="${escapeHtml(item.id)}">
        <div class="history-copy">
          <small>${escapeHtml(item.provider)} &middot; ${escapeHtml(item.language || item.script)} &middot; ${escapeHtml(new Date(item.created_at).toLocaleString())}</small>
          <p style="${textStyle}" data-history-text-id="${escapeHtml(item.id)}">${escapeHtml(displayText)}</p>
          <div class="history-style-controls">
            <select class="size-picker" data-history-id="${escapeHtml(item.id)}">
              ${FONT_SIZES.map((s) => `<option value="${s}"${s === item.font_size ? " selected" : ""}>${s}</option>`).join("")}
            </select>
            <button type="button" class="font-trigger" data-history-id="${escapeHtml(item.id)}" data-subset="${escapeHtml(item.script)}">
              <span class="font-trigger-label">${escapeHtml(item.font_family)}</span>
              <span class="font-trigger-arrow">&#9662;</span>
            </button>
            <select class="braille-picker" data-history-id="${escapeHtml(item.id)}">
              ${historyBrailleOptions(item)}
            </select>
          </div>
        </div>
        <div class="history-actions">
          <button type="button" class="history-send-button" data-history-id="${escapeHtml(item.id)}" ${disableSend ? "disabled" : ""}>Send to Robot</button>
          <button type="button" class="history-delete-button" data-history-id="${escapeHtml(item.id)}">Delete</button>
        </div>
      </div>`;
}

function renderFontList(fonts, selectedFamily, { hersheyFonts = [] } = {}) {
  let html = "";

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
  updateStyledText(transcript, {
    text: item.text,
    fontFamily: item.font_family,
    fontSize: item.font_size,
  });

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
  updateHistoryText(id, { fontFamily: family });
  const historyTrigger = historyList.querySelector(`.font-trigger[data-history-id="${id}"] .font-trigger-label`);
  if (historyTrigger) historyTrigger.textContent = family;
  if (currentTranscriptId === id) {
    updateStyledText(transcript, { fontFamily: family });
    transcriptFontTrigger.querySelector(".font-trigger-label").textContent = family;
  }
  updateHistoryItem(id, { font_family: family, font_url: url });
}

function clearCurrentTranscript() {
  currentTranscriptId = null;
  braillePreviewActive = false;
  updateStyledText(transcript, {
    text: DEFAULT_TRANSCRIPT_TEXT,
    fontFamily: "",
    fontSize: "",
  });
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
  historyList.innerHTML = items.map((item) => renderHistoryItem(item, disableSend)).join("");

  updateHistoryActionButtons();
}

function hydrateBrailleHistoryRows(items = transcriptHistory) {
  items.forEach((item) => {
    if (!item || item.braille_grade === "off" || item.braille_text) return;
    fetchBraillePreview(item.text, item.language, Number(item.braille_grade))
      .then((brailleText) => {
        setHistoryBrailleText(item, brailleText);
      })
      .catch(() => {});
  });
}

function syncRobotControls() {
  const robotBusy = activeRobotAction !== null;
  const canPair = !robotBusy;
  const canRefresh = !robotBusy;
  const canUnpair = !robotBusy && Boolean(pairedRobot);
  const canSendTranscript = !robotBusy && Boolean(pairedRobot) && robotConnected && currentTranscriptId !== null;
  const canControlMotion = Boolean(pairedRobot) && robotConnected && !robotJobInFlight;
  const canCalibratePen = Boolean(pairedRobot) && robotConnected && !robotJobInFlight;

  discoverRobotsButton.disabled = robotBusy;
  pairRobotButton.disabled = !canPair;
  refreshRobotButton.disabled = !canRefresh;
  unpairRobotButton.disabled = !canUnpair;
  sendTranscriptButton.disabled = !canSendTranscript;
  homeRobotButton.disabled = !canControlMotion;
  calibrateRobotButton.disabled = !canControlMotion;
  penServoSlider.disabled = !canCalibratePen;
  penSaveUpButton.disabled = !canCalibratePen;
  penSaveDownButton.disabled = !canCalibratePen;
  penSavePunchButton.disabled = !canCalibratePen;
  if (!canCalibratePen) {
    pendingPenDuty = null;
  }
  if (penCalibrationPanel && !penCalibrationPanel.hidden) {
    if (!pairedRobot || !robotConnected) {
      setPenCalibrationMessage("");
    } else if (robotJobInFlight) {
      setPenCalibrationMessage(PEN_CALIBRATION_DISABLED_TEXT);
    } else if (penCalibrationMessage?.textContent === PEN_CALIBRATION_DISABLED_TEXT) {
      setPenCalibrationMessage("");
    }
  }
  if (!robotJobInFlight) abortRobotButton.disabled = true;
  if (previewSendButton) {
    const hasPreview = Boolean(currentPreviewData?.operations?.length);
    previewSendButton.disabled = !(hasPreview && Boolean(pairedRobot) && robotConnected && !robotJobInFlight);
  }
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
    penCalibrationPanel.hidden = true;
    penConfigInitialized = false;
    setPenCalibrationMessage("");
    if (payload.warning) {
      robotStatus.textContent = payload.warning;
    } else if (!preserveStatus) {
      robotStatus.textContent = DEFAULT_ROBOT_STATUS_TEXT;
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

  const motionStatus = payload.status?.motion?.status;
  if ((motionStatus === "running" || motionStatus === "queued") && !robotJobInFlight) {
    startJobPolling();
  }

  loadPenConfig();
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
  hydrateBrailleHistoryRows(transcriptHistory);
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
    robotStatus.textContent = NO_TRANSCRIPT_TEXT;
    return;
  }
  if (!pairedRobot || !robotConnected) {
    robotStatus.textContent = UNREACHABLE_ROBOT_TEXT;
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

function stopJobPolling() {
  if (robotJobPollTimer !== null) {
    window.clearTimeout(robotJobPollTimer);
    robotJobPollTimer = null;
  }
}

function isTerminalStatus(status) {
  return status === "complete" || status === "failed" || status === "aborted" || status === "idle" || !status;
}

async function pollRobotJob() {
  let data;
  try {
    data = await fetchJson("/robot/job");
  } catch (e) {
    robotJobPollTimer = window.setTimeout(pollRobotJob, 1500);
    return;
  }
  lastRobotJobStatus = data;
  updateRobotJobUi(data);

  if (robotJobInPreviewMode && currentPreviewData) {
    updatePreviewWithLiveRobot(data);
  }

  if (isTerminalStatus(data.status)) {
    if (robotJobInPreviewMode) {
      finishLivePreview(data);
    }
    onRobotJobTerminal(data);
    robotJobInFlight = false;
    robotJobInPreviewMode = false;
    syncRobotControls();
    return;
  }

  robotJobPollTimer = window.setTimeout(pollRobotJob, 500);
}

function startJobPolling({ inPreviewMode = false } = {}) {
  stopJobPolling();
  robotJobInFlight = true;
  robotJobInPreviewMode = inPreviewMode;
  syncRobotControls();
  pollRobotJob();
}

function updateRobotJobUi(data) {
  const status = data?.status;
  const kind = data?.kind || "job";
  const active = Boolean(status && status !== "idle");
  const running = status === "running" || status === "queued";
  const total = data?.total_ops || 0;

  robotJobIndicator.hidden = !active;
  robotJobIndicator.textContent = !active
    ? ""
    : running && total > 0
      ? `${kind}: ${data.op_index || 0}/${total} (${data.progress_pct || 0}%)`
      : `${kind}: ${status}`;

  abortRobotButton.disabled = !(data && data.status === "running");

  if (!previewModal.hidden && previewJobStatus) {
    previewJobStatus.hidden = !active;
    if (!active) {
      previewJobStatus.textContent = "";
    } else if (status === "queued") {
      previewJobStatus.textContent = "Queued on robot...";
    } else if (status === "running") {
      previewJobStatus.textContent = total > 0
        ? `Drawing: ${data.op_index || 0}/${total} ops (${data.progress_pct || 0}%)`
        : "Drawing...";
    } else if (status === "complete") {
      previewJobStatus.textContent = "Done.";
    } else if (status === "failed") {
      previewJobStatus.textContent = `Failed: ${data.error || "unknown error"}`;
    } else if (status === "aborted") {
      previewJobStatus.textContent = "Aborted.";
    }
  }
}

function updatePreviewWithLiveRobot(data) {
  if (!previewAnimationState || !currentPreviewData) return;
  const opIdx = Math.max(0, Math.min(data.op_index || 0, currentPreviewData.operations.length));
  previewAnimationState.completedOps = currentPreviewData.operations.slice(0, opIdx).map((op) => ({
    type: op.type,
    points: op.points,
    point: op.point,
  }));
  previewAnimationState.currentSegIndex = opIdx;
  previewAnimationState.currentSegProgress = 0;
  if (Array.isArray(data.position_mm) && data.position_mm.length === 2) {
    previewAnimationState.toolheadPos = data.position_mm;
  }
  drawFrame(previewCanvas.getContext("2d"), previewCanvas, previewAnimationState);
}

function finishLivePreview(data) {
  if (!previewAnimationState || !currentPreviewData) return;
  previewAnimationState.completedOps = (currentPreviewData.operations || []).map((op) => ({
    type: op.type,
    points: op.points,
    point: op.point,
  }));
  previewAnimationState.currentSegIndex = (currentPreviewData.operations || []).length;
  previewAnimationState.done = true;
  if (Array.isArray(data.position_mm) && data.position_mm.length === 2) {
    previewAnimationState.toolheadPos = data.position_mm;
  }
  drawFrame(previewCanvas.getContext("2d"), previewCanvas, previewAnimationState);
}

function onRobotJobTerminal(data) {
  if (!data) return;
  const kind = data.kind || "job";
  if (data.kind === "calibrate" && data.result) {
    const r = data.result;
    const x = typeof r.travel_x_mm === "number" ? r.travel_x_mm.toFixed(1) : "?";
    const y = typeof r.travel_y_mm === "number" ? r.travel_y_mm.toFixed(1) : "?";
    robotStatus.textContent = `Calibration: travel X=${x}mm, Y=${y}mm, ${r.steps_per_mm} steps/mm`;
  } else if (data.status === "complete") {
    robotStatus.textContent = `${kind} complete.`;
  } else if (data.status === "failed") {
    robotStatus.textContent = `${kind} failed: ${data.error || "unknown error"}`;
  } else if (data.status === "aborted") {
    robotStatus.textContent = `${kind} aborted.`;
  }
}

async function homeRobot() {
  if (!pairedRobot || !robotConnected) {
    robotStatus.textContent = UNREACHABLE_ROBOT_TEXT;
    return;
  }
  try {
    robotStatus.textContent = "Homing...";
    const resp = await fetchJson("/robot/home", { method: "POST" });
    robotJobIndicator.hidden = false;
    robotJobIndicator.textContent = `home: queued (${resp.job_id || ""})`;
    startJobPolling();
  } catch (e) {
    robotStatus.textContent = e.message || "Home failed.";
  }
}

async function calibrateRobot() {
  if (!pairedRobot || !robotConnected) {
    robotStatus.textContent = UNREACHABLE_ROBOT_TEXT;
    return;
  }
  try {
    robotStatus.textContent = "Calibrating (full sweep)...";
    const resp = await fetchJson("/robot/calibrate", { method: "POST" });
    robotJobIndicator.hidden = false;
    robotJobIndicator.textContent = `calibrate: queued (${resp.job_id || ""})`;
    startJobPolling();
  } catch (e) {
    robotStatus.textContent = e.message || "Calibrate failed.";
  }
}

async function abortRobotJob() {
  try {
    await fetchJson("/robot/abort", { method: "POST" });
  } catch (e) {
    robotStatus.textContent = e.message || "Abort failed.";
  }
}

let penSetInFlight = false;
let pendingPenDuty = null;
let lastPenDutySent = null;
let penConfigInitialized = false;

async function loadPenConfig() {
  if (!pairedRobot || !robotConnected) return;
  try {
    const data = await fetchJson("/robot/pen/config");
    const minDuty = Number(data.min_duty ?? DEFAULT_PEN_DUTY_MIN);
    const maxDuty = Number(data.max_duty ?? DEFAULT_PEN_DUTY_MAX);
    penServoSlider.min = String(minDuty);
    penServoSlider.max = String(maxDuty);
    let sliderDuty = Number(penServoSlider.value);
    if (!penConfigInitialized || !Number.isFinite(sliderDuty)) {
      sliderDuty = Number(data.current_duty ?? data.pen_up_duty ?? data.pen_down_duty ?? data.punch_duty ?? 8000);
      penConfigInitialized = true;
    }
    sliderDuty = Math.min(maxDuty, Math.max(minDuty, sliderDuty));
    penServoSlider.value = String(sliderDuty);
    penServoValue.textContent = String(sliderDuty);
    lastPenDutySent = Number(data.current_duty ?? sliderDuty);
    penUpValue.textContent = data.pen_up_duty || "?";
    penDownValue.textContent = data.pen_down_duty || "?";
    penPunchValue.textContent = data.punch_duty || "?";
    penCalibrationPanel.hidden = false;
    penCalibrationStatus.style.color = "";
    setPenCalibrationMessage("");
  } catch {
    penCalibrationPanel.hidden = true;
    setPenCalibrationMessage("");
  }
  syncRobotControls();
}

async function flushPenSet() {
  if (penSetInFlight || pendingPenDuty === null || !pairedRobot || !robotConnected) return;
  const duty = pendingPenDuty;
  pendingPenDuty = null;
  if (duty === lastPenDutySent) return;
  penSetInFlight = true;
  try {
    await fetchJson("/robot/pen/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duty }),
    });
    lastPenDutySent = duty;
    penCalibrationStatus.style.color = "";
    setPenCalibrationMessage("");
  } catch (e) {
    setPenCalibrationMessage("Error: " + (e.message || "pen/set failed"), true);
  } finally {
    penSetInFlight = false;
    if (pendingPenDuty !== null && pendingPenDuty !== lastPenDutySent) {
      void flushPenSet();
    }
  }
}

function onPenSliderInput() {
  const duty = Number(penServoSlider.value);
  penServoValue.textContent = duty;
  pendingPenDuty = duty;
  void flushPenSet();
}

async function savePenUp() {
  const duty = Number(penServoSlider.value);
  try {
    const data = await fetchJson("/robot/pen/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pen_up_duty: duty }),
    });
    penUpValue.textContent = data.pen_up_duty || duty;
    penCalibrationStatus.style.color = "";
    setPenCalibrationMessage(`Saved pen-up at ${duty}.`);
  } catch (e) {
    setPenCalibrationMessage(e.message || "Unable to save pen-up position.", true);
  }
}

async function savePenDown() {
  const duty = Number(penServoSlider.value);
  try {
    const data = await fetchJson("/robot/pen/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pen_down_duty: duty }),
    });
    penDownValue.textContent = data.pen_down_duty || duty;
    penCalibrationStatus.style.color = "";
    setPenCalibrationMessage(`Saved writing depth at ${duty}.`);
  } catch (e) {
    setPenCalibrationMessage(e.message || "Unable to save writing depth.", true);
  }
}

async function savePenPunch() {
  const duty = Number(penServoSlider.value);
  try {
    const data = await fetchJson("/robot/pen/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ punch_duty: duty }),
    });
    const savedDuty = Number(data.punch_duty || duty);
    penPunchValue.textContent = savedDuty;
    penServoSlider.value = String(savedDuty);
    penServoValue.textContent = String(savedDuty);
    lastPenDutySent = savedDuty;
    penCalibrationStatus.style.color = "";
    setPenCalibrationMessage(`Saved braille depth at ${savedDuty}.`);
  } catch (e) {
    setPenCalibrationMessage(e.message || "Unable to save braille depth.", true);
  }
}

penServoSlider.addEventListener("input", onPenSliderInput);
penSaveUpButton.addEventListener("click", savePenUp);
penSaveDownButton.addEventListener("click", savePenDown);
penSavePunchButton.addEventListener("click", savePenPunch);


async function sendPreviewToRobot() {
  if (!currentPreviewData || !currentPreviewData.operations || currentPreviewData.operations.length === 0) {
    if (previewJobStatus) {
      previewJobStatus.hidden = false;
      previewJobStatus.textContent = "No preview generated yet.";
    }
    return;
  }
  if (!pairedRobot || !robotConnected) {
    if (previewJobStatus) {
      previewJobStatus.hidden = false;
      previewJobStatus.textContent = UNREACHABLE_ROBOT_TEXT;
    }
    return;
  }

  stopPreviewAnimation();
  if (previewAnimationState) {
    previewAnimationState.completedOps = [];
    previewAnimationState.currentSegIndex = 0;
    previewAnimationState.currentSegProgress = 0;
    previewAnimationState.toolheadPos = null;
    previewAnimationState.done = false;
    previewAnimationState.playing = false;
    drawFrame(previewCanvas.getContext("2d"), previewCanvas, previewAnimationState);
  }

  try {
    previewSendButton.disabled = true;
    if (previewJobStatus) {
      previewJobStatus.hidden = false;
      previewJobStatus.textContent = "Submitting...";
    }
    const resp = await fetchJson("/robot/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: currentPreviewData.mode || "write",
        operations: currentPreviewData.operations,
      }),
    });
    if (previewJobStatus) {
      previewJobStatus.textContent = `Queued on robot: ${resp.job_id || ""}`;
    }
    startJobPolling({ inPreviewMode: true });
  } catch (e) {
    if (previewJobStatus) {
      previewJobStatus.hidden = false;
      previewJobStatus.textContent = e.message || "Send failed.";
    }
    syncRobotControls();
  }
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
    updateHistoryText(id, { fontSize: size });
    if (currentTranscriptId === id) {
      updateStyledText(transcript, { fontSize: size });
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
    const val = braillePicker.value;
    const grade = val === "off" ? "off" : Number(val);
    updateHistoryItem(id, { braille_grade: grade });

    if (grade === "off") {
      updateHistoryItem(id, { braille_text: "" });
      restoreHistoryText(item);
    } else {
      braillePicker.disabled = true;
      fetchBraillePreview(item.text, item.language, grade)
        .then((brailleText) => {
          setHistoryBrailleText(item, brailleText);
        })
        .catch(() => {})
        .finally(() => { braillePicker.disabled = false; });
    }

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
  updateStyledText(transcript, { fontSize: size });
  if (currentTranscriptId) {
    updateHistoryText(currentTranscriptId, { fontSize: size });
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
        const url = buildGoogleFontsUrl(family);
        ensureFont(family, url);
        updateStyledText(transcript, { fontFamily: family });
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
  if (currentTranscriptId) {
    const grade = brailleActive() ? brailleGrade() : "off";
    updateHistoryItem(currentTranscriptId, { braille_grade: grade });
    const historyBraille = historyList.querySelector(`.braille-picker[data-history-id="${currentTranscriptId}"]`);
    if (historyBraille) historyBraille.value = String(grade === "off" ? "off" : grade);
    const item = findTranscriptInHistory(currentTranscriptId);
    if (item) {
      if (grade === "off") {
        updateHistoryItem(currentTranscriptId, { braille_text: "" });
        restoreHistoryText(item);
      } else {
        fetchBraillePreview(item.text, item.language, grade)
          .then((brailleText) => {
            setHistoryBrailleText(item, brailleText);
          })
          .catch(() => {});
      }
    }
  }
});

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
  syncRobotControls();
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

function stepPreviewAnimation(state, ctx, canvas, timestamp) {
  if (!state.playing || state.done) {
    state.animFrameId = null;
    return;
  }

  if (!state.lastTime) state.lastTime = timestamp;
  const dt = timestamp - state.lastTime;
  state.lastTime = timestamp;

  advanceAnimation(state, state.pixelsPerMs * state.speed * dt);
  drawFrame(ctx, canvas, state);

  if (!state.done) {
    state.animFrameId = requestAnimationFrame((ts) => stepPreviewAnimation(state, ctx, canvas, ts));
  } else {
    previewPlayPause.textContent = "\u25B6";
  }
}

function startPreviewAnimation(data) {
  stopPreviewAnimation();

  const canvas = previewCanvas;
  const ctx = canvas.getContext("2d");
  const paper = data.paper;

  const padding = 20;
  const scaleX = (canvas.width - 2 * padding) / paper.width;
  const scaleY = (canvas.height - 2 * padding) / paper.height;
  const scale = Math.min(scaleX, scaleY);
  const offsetX = padding + (canvas.width - 2 * padding - paper.width * scale) / 2;
  const offsetY = padding + (canvas.height - 2 * padding - paper.height * scale) / 2;

  function toCanvas(x, y) {
    return [offsetX + x * scale, offsetY + y * scale];
  }

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
    completedOps: [],
    toolheadPos: null,
    animFrameId: null,
    lastTime: null,
    pixelsPerMs: 0.15,
  };

  previewAnimationState = state;
  previewPlayPause.textContent = "\u23F8";
  drawFrame(ctx, canvas, state);
  state.animFrameId = requestAnimationFrame((timestamp) => stepPreviewAnimation(state, ctx, canvas, timestamp));
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

  const [px0, py0] = toCanvas(0, 0);
  const [px1, py1] = toCanvas(paper.width, paper.height);
  ctx.fillStyle = "white";
  ctx.fillRect(px0, py0, px1 - px0, py1 - py0);
  ctx.strokeStyle = "#999";
  ctx.lineWidth = 1;
  ctx.strokeRect(px0, py0, px1 - px0, py1 - py0);

  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#ccc";
  ctx.lineWidth = 0.5;
  const [mx0, my0] = toCanvas(margins.left, margins.top);
  const [mx1, my1] = toCanvas(paper.width - margins.right, paper.height - margins.bottom);
  ctx.strokeRect(mx0, my0, mx1 - mx0, my1 - my0);
  ctx.setLineDash([]);

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

  for (const op of state.completedOps) {
    if (op.type === "travel") {
      drawTravelPath(ctx, state, op.points);
    } else if (op.type === "draw") {
      drawDrawPath(ctx, state, op.points);
    } else if (op.type === "punch" && !(state.penTipPx > 0.5)) {
      drawPunchPoint(ctx, state, op.point);
    }
  }

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
  return Math.round(px * 0.25 * 2) / 2;
}

function itemBrailleActive(item) {
  return item.braille_grade !== "off" && item.braille_grade != null;
}

function openPreviewModal(item) {
  previewTranscriptItem = item;
  previewModal.hidden = false;
  customPaperFields.hidden = previewPaperSize.value !== "Custom";
  if (previewJobStatus) {
    previewJobStatus.hidden = true;
    previewJobStatus.textContent = "";
  }

  const isBraille = itemBrailleActive(item);

  if (item.font_size) {
    previewFontSize.value = pxToMm(item.font_size);
  }

  const fontLabel = previewFontTrigger.closest("label");
  if (isBraille) {
    setElementDisplay(fontLabel, false);
  } else {
    setElementDisplay(fontLabel, true);
    setPreviewFont(item.font_family);
    previewFontTrigger.dataset.subset = item.script || "latin";
  }

  const renderModeLabel = previewRenderMode.closest("label");
  const fontSizeLabel = previewFontSize.closest("label");
  const penTipLabel = previewPenTip.closest("label");
  if (isBraille) {
    setElementDisplay(renderModeLabel, false);
    setElementDisplay(fontSizeLabel, false);
    setElementDisplay(penTipLabel, false);
  } else {
    setElementDisplay(renderModeLabel, true);
    setElementDisplay(fontSizeLabel, true);
    setElementDisplay(penTipLabel, true);
  }

  fetchPreview(item);
}

function closePreviewModal() {
  previewModal.hidden = true;
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
previewModalClose.addEventListener("click", closePreviewModal);
previewModal.addEventListener("click", (e) => {
  if (e.target === previewModal) closePreviewModal();
});

previewPlayPause.addEventListener("click", () => {
  if (!previewAnimationState) return;
  if (previewAnimationState.done) {
    if (currentPreviewData) startPreviewAnimation(currentPreviewData);
    return;
  }
  previewAnimationState.playing = !previewAnimationState.playing;
  previewPlayPause.textContent = previewAnimationState.playing ? "\u23F8" : "\u25B6";
  if (previewAnimationState.playing) {
    previewAnimationState.lastTime = null;
    previewAnimationState.animFrameId = requestAnimationFrame((timestamp) =>
      stepPreviewAnimation(previewAnimationState, previewCanvas.getContext("2d"), previewCanvas, timestamp)
    );
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
  customPaperFields.hidden = previewPaperSize.value !== "Custom";
  debouncedRefreshPreview();
});
for (const el of [
  previewPaperWidth, previewPaperHeight, previewRenderMode,
  previewFontSize, previewPenTip,
  previewMarginTop, previewMarginRight, previewMarginBottom, previewMarginLeft,
  previewOffsetX, previewOffsetY,
]) {
  el.addEventListener("change", debouncedRefreshPreview);
  el.addEventListener("input", debouncedRefreshPreview);
}
previewFontTrigger.addEventListener("click", () => {
  const subset = previewFontTrigger.dataset.subset || "latin";
  const currentFamily = previewFontValue.value;
  openFontPicker(previewFontTrigger, subset, currentFamily, setPreviewFont, {
    hersheyFonts: cachedHersheyFonts || [],
  });
});

function handleSendToRobot(item) {
  if (!item) {
    robotStatus.textContent = NO_TRANSCRIPT_TEXT;
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
homeRobotButton.addEventListener("click", homeRobot);
calibrateRobotButton.addEventListener("click", calibrateRobot);
abortRobotButton.addEventListener("click", abortRobotJob);
previewSendButton.addEventListener("click", sendPreviewToRobot);
transcriptSizePicker.innerHTML = FONT_SIZES.map(
  (s) => `<option value="${s}"${s === DEFAULT_FONT_SIZE ? " selected" : ""}>${s}</option>`
).join("");
loadHistory();
loadRobotState();
loadPaperSizes();
