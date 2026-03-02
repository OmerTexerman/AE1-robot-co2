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

let mediaRecorder;
let audioChunks = [];
let recordedMimeType = "audio/webm";
let currentTranscript = null;
let pairedRobot = null;
let discoveredRobotItems = [];

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

function currentCandidatePorts() {
  const port = Number(robotPortInput.value || 8080);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return [];
  }
  return [port];
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = "<p>No transcripts yet.</p>";
    return;
  }
  historyList.innerHTML = items
    .map(
      (i) => `<div class="history-item">
        <small>${escapeHtml(i.provider)} &middot; ${escapeHtml(i.language || i.script)} &middot; ${escapeHtml(new Date(i.created_at).toLocaleString())}</small>
        <p style="font-family:'${escapeHtml(i.font_family)}',sans-serif">${escapeHtml(i.text)}</p>
      </div>`
    )
    .join("");
}

function renderRobotState(payload) {
  pairedRobot = payload.paired ? payload.robot : null;

  if (!payload.paired || !payload.robot) {
    robotConnection.textContent = "No robot paired.";
    robotStatus.textContent = "Pair the speech app to your Pico 2 W over the laptop hotspot or local network.";
    robotMeta.innerHTML = "";
    unpairRobotButton.disabled = true;
    sendTranscriptButton.disabled = true;
    return;
  }

  robotHostInput.value = payload.robot.host;
  robotPortInput.value = payload.robot.port;
  robotClientNameInput.value = payload.robot.client_name;
  robotConnection.textContent = payload.connected ? "Robot connected." : "Robot paired, but currently unreachable.";
  robotStatus.textContent = payload.error || (payload.status ? "Robot status is live." : "Robot is paired.");
  robotMeta.innerHTML = `
    <div class="meta-row"><strong>Device:</strong> ${escapeHtml(payload.robot.device_name)}</div>
    <div class="meta-row"><strong>ID:</strong> ${escapeHtml(payload.robot.device_id)}</div>
    <div class="meta-row"><strong>Endpoint:</strong> ${escapeHtml(payload.robot.base_url)}</div>
    <div class="meta-row"><strong>Paired:</strong> ${escapeHtml(new Date(payload.robot.paired_at).toLocaleString())}</div>
  `;
  unpairRobotButton.disabled = false;
  sendTranscriptButton.disabled = !payload.connected || !currentTranscript;
}

function useDiscoveredRobot(index) {
  const robot = discoveredRobotItems[index];
  if (!robot) {
    return;
  }

  robotHostInput.value = robot.host;
  robotPortInput.value = robot.port;
  robotStatus.textContent = `Loaded ${robot.device_name}. Enter the pairing code to complete pairing.`;
}

function renderDiscoveredRobots(items) {
  discoveredRobotItems = items;

  if (!items.length) {
    discoveredRobots.innerHTML = "<p>No robots discovered yet.</p>";
    return;
  }

  discoveredRobots.innerHTML = items
    .map(
      (item, index) => `
        <div class="discovered-item">
          <div class="discovered-copy">
            <strong>${escapeHtml(item.device_name)}</strong>
            <span>${escapeHtml(item.host)}:${escapeHtml(String(item.port))}</span>
          </div>
          <button type="button" class="use-robot-button" data-robot-index="${index}">
            Use This Robot
          </button>
        </div>
      `
    )
    .join("");

  document.querySelectorAll(".use-robot-button").forEach((button) => {
    button.addEventListener("click", () => useDiscoveredRobot(Number(button.dataset.robotIndex)));
  });
}

async function loadRobotState() {
  try {
    const payload = await fetchJson("/robot");
    renderRobotState(payload);
  } catch (error) {
    robotConnection.textContent = "Robot status unavailable.";
    robotStatus.textContent = error.message || "Unable to load robot state.";
  }
}

async function discoverRobots() {
  robotStatus.textContent = "Scanning the laptop hotspot for Pico robots...";
  discoverRobotsButton.disabled = true;

  try {
    const payload = await fetchJson("/robot/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ports: currentCandidatePorts() }),
    });

    renderDiscoveredRobots(payload.items);
    robotStatus.textContent = payload.items.length
      ? "Discovery complete. Pick a robot and pair it."
      : "No robots replied. Check that the Pico joined the laptop hotspot.";
  } catch (error) {
    robotStatus.textContent = error.message || "Robot discovery failed.";
  } finally {
    discoverRobotsButton.disabled = false;
  }
}

async function pairRobot() {
  robotStatus.textContent = "Pairing with robot...";
  pairRobotButton.disabled = true;

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
    robotStatus.textContent = "Pairing complete.";
  } catch (error) {
    robotStatus.textContent = error.message || "Pairing failed.";
  } finally {
    pairRobotButton.disabled = false;
  }
}

async function unpairRobot() {
  robotStatus.textContent = "Removing robot pairing...";
  unpairRobotButton.disabled = true;

  try {
    const payload = await fetchJson("/robot/unpair", { method: "POST" });
    renderRobotState(payload);
    robotStatus.textContent = payload.warning || "Robot unpaired.";
  } catch (error) {
    robotStatus.textContent = error.message || "Unpair failed.";
  } finally {
    unpairRobotButton.disabled = !pairedRobot;
  }
}

async function sendTranscriptToRobot() {
  if (!currentTranscript) {
    robotStatus.textContent = "Record and transcribe something first.";
    return;
  }

  robotStatus.textContent = "Sending transcript to robot...";
  sendTranscriptButton.disabled = true;

  try {
    const payload = await fetchJson("/robot/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: currentTranscript.text,
        font_family: currentTranscript.font_family,
        script: currentTranscript.script,
      }),
    });

    robotStatus.textContent = `Robot accepted job ${payload.job_id}.`;
  } catch (error) {
    robotStatus.textContent = error.message || "Unable to send transcript.";
  } finally {
    sendTranscriptButton.disabled = !(pairedRobot && currentTranscript);
  }
}

async function loadHistory() {
  try {
    const data = await fetchJson("/history");
    data.items.forEach((i) => ensureFont(i.font_family, i.font_url));
    renderHistory(data.items);
  } catch {
    historyList.innerHTML = "<p>Unable to load history.</p>";
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

    ensureFont(data.font_family, data.font_url);
    transcript.textContent = data.text;
    transcript.style.fontFamily = `"${data.font_family}", sans-serif`;
    currentTranscript = data;
    status.textContent = "Done.";
    sendTranscriptButton.disabled = !pairedRobot;
    await loadHistory();
  } catch (e) {
    transcript.textContent = "Transcription failed.";
    status.textContent = e.message;
    currentTranscript = null;
    sendTranscriptButton.disabled = true;
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

recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
pairRobotButton.addEventListener("click", pairRobot);
discoverRobotsButton.addEventListener("click", discoverRobots);
refreshRobotButton.addEventListener("click", loadRobotState);
unpairRobotButton.addEventListener("click", unpairRobot);
sendTranscriptButton.addEventListener("click", sendTranscriptToRobot);
loadHistory();
loadRobotState();
window.setInterval(loadRobotState, 8000);
