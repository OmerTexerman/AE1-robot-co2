const recordButton = document.getElementById("recordButton");
const stopButton = document.getElementById("stopButton");
const statusText = document.getElementById("statusText");
const statusDot = document.getElementById("statusDot");
const transcriptText = document.getElementById("transcriptText");
const scriptLabel = document.getElementById("scriptLabel");
const providerSelect = document.getElementById("providerSelect");
const historyList = document.getElementById("historyList");
const progressPanel = document.getElementById("progressPanel");
const progressTitle = document.getElementById("progressTitle");
const progressDetail = document.getElementById("progressDetail");
const progressElapsed = document.getElementById("progressElapsed");

let mediaRecorder;
let audioChunks = [];
let recordedMimeType = "audio/webm";
let progressInterval;
let progressStartedAt = 0;

function setStatus(message, state) {
  statusText.textContent = message;
  statusDot.dataset.state = state;
}

function setProgress(title, detail) {
  progressTitle.textContent = title;
  progressDetail.textContent = detail;
}

function updateProgressElapsed() {
  if (!progressStartedAt) {
    progressElapsed.textContent = "0s";
    return;
  }

  const seconds = Math.floor((Date.now() - progressStartedAt) / 1000);
  progressElapsed.textContent = `${seconds}s`;

  if (seconds >= 20) {
    progressDetail.textContent = "Still working. Local Whisper can take longer on first run.";
  } else if (seconds >= 8 && progressDetail.textContent === "Running speech recognition...") {
    progressDetail.textContent = "Still transcribing. Larger models may take a bit.";
  }
}

function showProgress(title, detail) {
  progressPanel.hidden = false;
  progressStartedAt = Date.now();
  setProgress(title, detail);
  updateProgressElapsed();
  clearInterval(progressInterval);
  progressInterval = window.setInterval(updateProgressElapsed, 1000);
}

function updateProgress(detail) {
  progressDetail.textContent = detail;
}

function hideProgress() {
  progressPanel.hidden = true;
  progressStartedAt = 0;
  clearInterval(progressInterval);
  progressElapsed.textContent = "0s";
}

function freezeProgress() {
  progressStartedAt = 0;
  clearInterval(progressInterval);
}

function ensureFont(fontFamily, fontUrl) {
  if (!fontUrl) {
    return;
  }

  const existing = document.querySelector(`link[data-font="${fontFamily}"]`);
  if (existing) {
    return;
  }

  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = fontUrl;
  link.dataset.font = fontFamily;
  document.head.appendChild(link);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = '<p class="history-empty">No transcripts yet.</p>';
    return;
  }

  historyList.innerHTML = items
    .map((item) => {
      return `
        <article class="history-item">
          <div class="history-meta">
            <span>${escapeHtml(item.provider)}</span>
            <span>${escapeHtml(item.script)}</span>
            <span>${escapeHtml(new Date(item.created_at).toLocaleString())}</span>
          </div>
          <p class="history-text" style="font-family: '${escapeHtml(item.font_family)}', sans-serif;">
            ${escapeHtml(item.text)}
          </p>
        </article>
      `;
    })
    .join("");
}

async function loadHistory() {
  try {
    const response = await fetch("/history");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unable to load history");
    }

    payload.items.forEach((item) => ensureFont(item.font_family, item.font_url));
    renderHistory(payload.items);
  } catch (_error) {
    historyList.innerHTML = '<p class="history-empty">Unable to load history.</p>';
  }
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setStatus("This browser does not support microphone access.", "error");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    recordedMimeType = mediaRecorder.mimeType || "audio/webm";
    audioChunks = [];

    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunks.push(event.data);
      }
    };

    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      await uploadAudio();
    };

    mediaRecorder.start();
    recordButton.disabled = true;
    stopButton.disabled = false;
    providerSelect.disabled = true;
    setStatus("Recording...", "recording");
    hideProgress();
  } catch (error) {
    setStatus(`Microphone access failed: ${error.message}`, "error");
    hideProgress();
  }
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state !== "recording") {
    return;
  }

  mediaRecorder.stop();
  stopButton.disabled = true;
  setStatus("Uploading audio...", "working");
  showProgress("Transcription in progress", "Uploading audio to the server...");
}

function extensionFromMimeType(mimeType) {
  if (mimeType.includes("mp4")) {
    return "mp4";
  }
  if (mimeType.includes("ogg")) {
    return "ogg";
  }
  if (mimeType.includes("mpeg")) {
    return "mp3";
  }
  if (mimeType.includes("wav")) {
    return "wav";
  }
  return "webm";
}

async function uploadAudio() {
  const audioBlob = new Blob(audioChunks, { type: recordedMimeType });
  const extension = extensionFromMimeType(recordedMimeType);
  const formData = new FormData();
  formData.append("audio", audioBlob, `speech.${extension}`);
  formData.append("provider", providerSelect.value);

  try {
    setStatus("Transcribing...", "working");
    updateProgress("Running speech recognition...");

    const response = await fetch("/transcribe", {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Unknown server error");
    }

    ensureFont(payload.font_family, payload.font_url);
    transcriptText.textContent = payload.text;
    transcriptText.style.fontFamily = `"${payload.font_family}", sans-serif`;
    scriptLabel.textContent = `Font: ${payload.font_family} (${payload.script}, ${payload.provider})`;
    setStatus("Transcription complete.", "ready");
    hideProgress();
    await loadHistory();
  } catch (error) {
    transcriptText.textContent = "Unable to transcribe the recording.";
    scriptLabel.textContent = "Font: unavailable";
    setStatus(error.message, "error");
    setProgress("Transcription failed", "The request stopped before a transcript was returned.");
    freezeProgress();
  } finally {
    recordButton.disabled = false;
    providerSelect.disabled = false;
    if (statusDot.dataset.state !== "error") {
      hideProgress();
    }
  }
}

recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);
loadHistory();
