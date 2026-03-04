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

const DEFAULT_TRANSCRIPT_TEXT = "Your text will appear here.";
const HISTORY_STORAGE_KEY = "speechAppTranscriptHistory";
const HISTORY_LIMIT = 12;
const FONT_SIZES = [14, 16, 18, 20, 24, 28, 32, 40];
const DEFAULT_FONT_SIZE = 20;
const DEFAULT_FONT_FAMILY = "Noto Sans";
const DEFAULT_ROBOT_PORT = 8080;

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

function renderFontList(fonts, selectedFamily) {
  if (!fonts.length) {
    fontPickerList.innerHTML = '<div class="font-picker-empty">No fonts found</div>';
    return;
  }
  fontPickerList.innerHTML = fonts
    .map(
      (f) =>
        `<div class="font-picker-item${f.family === selectedFamily ? " selected" : ""}" data-family="${escapeHtml(f.family)}">${escapeHtml(f.family)}</div>`
    )
    .join("");
}

async function openFontPicker(triggerEl, subset, currentFamily, onSelect) {
  if (activeFontPicker && activeFontPicker.triggerEl === triggerEl) {
    closeFontPicker();
    return;
  }

  activeFontPicker = { triggerEl, subset, currentFamily, onSelect };
  fontPickerSearch.value = "";
  fontPickerList.innerHTML = '<div class="font-picker-empty">Loading...</div>';
  fontPickerPanel.classList.add("open");

  // position near the trigger
  const rect = triggerEl.getBoundingClientRect();
  fontPickerPanel.style.top = (rect.bottom + window.scrollY + 4) + "px";
  fontPickerPanel.style.left = rect.left + "px";

  fontPickerSearch.focus();

  const cached = await getFontsForSubset(subset);
  const fonts = [...cached];
  // Ensure current font is in the list without mutating cache
  if (currentFamily && !fonts.some((f) => f.family === currentFamily)) {
    fonts.unshift({ family: currentFamily, category: "" });
  }
  activeFontPicker.allFonts = fonts;
  renderFontList(fonts, currentFamily);
}

function filterFontList() {
  if (!activeFontPicker?.allFonts) return;
  const q = fontPickerSearch.value.toLowerCase();
  const filtered = q
    ? activeFontPicker.allFonts.filter((f) => f.family.toLowerCase().includes(q))
    : activeFontPicker.allFonts;
  renderFontList(filtered, activeFontPicker.currentFamily);
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
            <button type="button" class="braille-toggle" data-history-id="${escapeHtml(i.id)}">Braille</button>
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
    if (!preserveStatus) {
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
  robotMeta.innerHTML = `
    <div class="meta-row"><strong>Device:</strong> ${escapeHtml(payload.robot.device_name)}</div>
    <div class="meta-row"><strong>ID:</strong> ${escapeHtml(payload.robot.device_id)}</div>
    <div class="meta-row"><strong>Endpoint:</strong> ${escapeHtml(payload.robot.base_url)}</div>
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
      (item) => `
        <div class="discovered-item">
          <div class="discovered-copy">
            <strong>${escapeHtml(item.device_name)}</strong>
            <span>${escapeHtml(item.host)}:${escapeHtml(String(item.port))}</span>
          </div>
          <button
            type="button"
            class="use-robot-button"
            data-robot-host="${escapeHtml(item.host)}"
            data-robot-port="${escapeHtml(String(item.port))}"
            data-robot-name="${escapeHtml(item.device_name)}"
          >
            Use This Robot
          </button>
        </div>
      `
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

async function pairRobot() {
  robotStatus.textContent = "Pairing with robot...";
  markRobotStateMutation();
  activeRobotAction = "pair";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: robotHostInput.value,
        port: Number(robotPortInput.value || DEFAULT_ROBOT_PORT),
        pairing_code: robotPairingCodeInput.value,
        client_name: robotClientNameInput.value,
      }),
    });

    robotPairingCodeInput.value = "";
    renderRobotState(payload);
    robotStatus.textContent = payload.connected ? "Pairing complete." : (payload.error || "Pairing saved, but the robot is currently unreachable.");
  } catch (error) {
    robotStatus.textContent = error.message || "Pairing failed.";
  } finally {
    activeRobotAction = null;
    syncRobotControls();
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

  robotStatus.textContent = brailleActive()
    ? "Sending Braille to robot..."
    : "Sending transcript to robot...";
  activeRobotAction = "render";
  syncRobotControls();

  try {
    const renderBody = brailleActive()
      ? {
          mode: "braille",
          text: transcriptToSend.text,
          language: transcriptToSend.language,
          grade: brailleGrade(),
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

    robotStatus.textContent = brailleActive()
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
    if (historyItem) sendTranscriptPayloadToRobot(historyItem);
    return;
  }

  const deleteButton = event.target.closest(".history-delete-button");
  if (deleteButton) {
    deleteTranscriptFromHistory(deleteButton.dataset.historyId || "");
    return;
  }

  const brailleBtn = event.target.closest(".braille-toggle[data-history-id]");
  if (brailleBtn) {
    const id = brailleBtn.dataset.historyId || "";
    const item = findTranscriptInHistory(id);
    if (!item) return;
    const textEl = historyList.querySelector(`[data-history-text-id="${id}"]`);
    if (!textEl) return;

    if (brailleBtn.classList.contains("active")) {
      // Restore original text
      brailleBtn.classList.remove("active");
      textEl.textContent = item.text;
      textEl.style.fontFamily = cssFontFamily(item.font_family);
    } else {
      // Fetch and show Braille preview
      brailleBtn.disabled = true;
      fetchBraillePreview(item.text, item.language, brailleGrade())
        .then((brailleText) => {
          brailleBtn.classList.add("active");
          textEl.textContent = brailleText;
          textEl.style.fontFamily = "";
        })
        .catch(() => {})
        .finally(() => { brailleBtn.disabled = false; });
    }
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
  if (!picker) return;
  const id = picker.dataset.historyId || "";
  const size = Number(picker.value);
  const textEl = historyList.querySelector(`[data-history-text-id="${id}"]`);
  if (textEl) textEl.style.fontSize = size + "px";
  if (currentTranscriptId === id) {
    transcript.style.fontSize = size + "px";
    transcriptSizePicker.value = String(size);
  }
  updateHistoryItem(id, { font_size: size });
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

discoveredRobots.addEventListener("click", (event) => {
  const button = event.target.closest(".use-robot-button");
  if (!button) {
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
});

recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
pairRobotButton.addEventListener("click", pairRobot);
discoverRobotsButton.addEventListener("click", discoverRobots);
refreshRobotButton.addEventListener("click", loadRobotState);
unpairRobotButton.addEventListener("click", unpairRobot);
sendTranscriptButton.addEventListener("click", sendTranscriptToRobot);
transcriptSizePicker.innerHTML = FONT_SIZES.map(
  (s) => `<option value="${s}"${s === DEFAULT_FONT_SIZE ? " selected" : ""}>${s}</option>`
).join("");
loadHistory();
loadRobotState();
