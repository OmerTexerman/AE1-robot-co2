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

const DEFAULT_TRANSCRIPT_TEXT = "Your text will appear here.";
const HISTORY_STORAGE_KEY = "speechAppTranscriptHistory";
const HISTORY_LIMIT = 12;

let mediaRecorder;
let audioChunks = [];
let recordedMimeType = "audio/webm";
let currentTranscript = null;
let transcriptHistory = [];
let pairedRobot = null;
let robotConnected = false;
let activeRobotAction = null;
let robotPollTimer = null;
let robotStateRequestInFlight = false;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function ensureFont(family, url) {
  if (!url || document.querySelector(`link[data-font="${family}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = url;
  link.dataset.font = family;
  document.head.appendChild(link);
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
  const port = Number(robotPortInput.value || 8080);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return 8080;
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

  return {
    id: typeof item.id === "string" && item.id ? item.id : historyItemId(),
    text,
    script: typeof item.script === "string" && item.script ? item.script : "latin",
    font_family: typeof item.font_family === "string" && item.font_family ? item.font_family : "Noto Sans",
    font_url: typeof item.font_url === "string" ? item.font_url : "",
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
  const disableSend = activeRobotAction !== null || robotStateRequestInFlight || !pairedRobot || !robotConnected;
  historyList.querySelectorAll(".history-send-button").forEach((button) => {
    button.disabled = disableSend;
  });
}

function setCurrentTranscript(item) {
  ensureFont(item.font_family, item.font_url);
  currentTranscript = item;
  transcript.textContent = item.text;
  transcript.style.fontFamily = `"${item.font_family}", sans-serif`;
  syncRobotControls();
}

function clearCurrentTranscript() {
  currentTranscript = null;
  transcript.textContent = DEFAULT_TRANSCRIPT_TEXT;
  transcript.style.fontFamily = "";
  syncRobotControls();
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
  if (currentTranscript?.id === id) {
    clearCurrentTranscript();
  }

  transcriptHistory = transcriptHistory.filter((item) => item.id !== id);
  persistTranscriptHistory();
  renderHistory(transcriptHistory);
}

function findTranscriptInHistory(id) {
  return transcriptHistory.find((item) => item.id === id) || null;
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = "<p>No transcripts yet.</p>";
    return;
  }

  const disableSend = activeRobotAction !== null || robotStateRequestInFlight || !pairedRobot || !robotConnected;
  historyList.innerHTML = items
    .map(
      (i) => `<div class="history-item" data-history-id="${escapeHtml(i.id)}">
        <div class="history-copy">
          <small>${escapeHtml(i.provider)} &middot; ${escapeHtml(i.language || i.script)} &middot; ${escapeHtml(new Date(i.created_at).toLocaleString())}</small>
          <p style="font-family:'${escapeHtml(i.font_family)}',sans-serif">${escapeHtml(i.text)}</p>
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
  const robotBusy = activeRobotAction !== null || robotStateRequestInFlight;
  const canPair = !robotBusy;
  const canRefresh = !robotBusy;
  const canUnpair = !robotBusy && Boolean(pairedRobot);
  const canSendTranscript = !robotBusy && Boolean(pairedRobot) && robotConnected && Boolean(currentTranscript);

  discoverRobotsButton.disabled = robotBusy;
  pairRobotButton.disabled = !canPair;
  refreshRobotButton.disabled = !canRefresh;
  unpairRobotButton.disabled = !canUnpair;
  sendTranscriptButton.disabled = !canSendTranscript;
  updateHistoryActionButtons();
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
    loadRobotState({ silent: true });
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
  const { silent = false } = options;
  if (robotStateRequestInFlight) {
    return;
  }

  robotStateRequestInFlight = true;
  syncRobotControls();
  try {
    const payload = await fetchJson("/robot");
    renderRobotState(payload, { preserveStatus: silent });
  } catch (error) {
    robotConnection.textContent = "Robot status unavailable.";
    robotConnected = false;
    if (!silent) {
      robotStatus.textContent = error.message || "Unable to load robot state.";
    }
    syncRobotControls();
  } finally {
    robotStateRequestInFlight = false;
    syncRobotControls();
    if (pairedRobot) {
      scheduleRobotPoll();
    }
  }
}

function loadHistory() {
  transcriptHistory = loadTranscriptHistory();
  persistTranscriptHistory();
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
  activeRobotAction = "pair";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        host: robotHostInput.value,
        port: Number(robotPortInput.value || 8080),
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

  robotStatus.textContent = "Sending transcript to robot...";
  activeRobotAction = "render";
  syncRobotControls();

  try {
    const payload = await fetchJson("/robot/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: transcriptToSend.text,
        font_family: transcriptToSend.font_family,
        script: transcriptToSend.script,
      }),
    });

    robotStatus.textContent = `Robot accepted job ${payload.job_id}.`;
  } catch (error) {
    robotStatus.textContent = error.message || "Unable to send transcript.";
  } finally {
    activeRobotAction = null;
    syncRobotControls();
  }
}

async function sendTranscriptToRobot() {
  await sendTranscriptPayloadToRobot(currentTranscript);
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
    currentTranscript = null;
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
    if (!historyItem) {
      return;
    }

    sendTranscriptPayloadToRobot(historyItem);
    return;
  }

  const deleteButton = event.target.closest(".history-delete-button");
  if (!deleteButton) {
    return;
  }

  deleteTranscriptFromHistory(deleteButton.dataset.historyId || "");
});

discoveredRobots.addEventListener("click", (event) => {
  const button = event.target.closest(".use-robot-button");
  if (!button) {
    return;
  }

  robotHostInput.value = button.dataset.robotHost || "";
  robotPortInput.value = button.dataset.robotPort || "8080";
  robotStatus.textContent = `Loaded ${button.dataset.robotName || "robot"}. Enter the pairing code to complete pairing.`;
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopRobotPolling();
    return;
  }

  if (pairedRobot) {
    loadRobotState({ silent: true });
  }
});

recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
pairRobotButton.addEventListener("click", pairRobot);
discoverRobotsButton.addEventListener("click", discoverRobots);
refreshRobotButton.addEventListener("click", loadRobotState);
unpairRobotButton.addEventListener("click", unpairRobot);
sendTranscriptButton.addEventListener("click", sendTranscriptToRobot);
loadHistory();
loadRobotState();
