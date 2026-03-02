const recordButton = document.getElementById("recordButton");
const stopButton = document.getElementById("stopButton");
const status = document.getElementById("status");
const transcript = document.getElementById("transcript");
const providerSelect = document.getElementById("providerSelect");
const historyList = document.getElementById("historyList");

let mediaRecorder;
let audioChunks = [];
let recordedMimeType = "audio/webm";

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

function renderHistory(items) {
  if (!items.length) {
    historyList.innerHTML = "<p>No transcripts yet.</p>";
    return;
  }
  historyList.innerHTML = items
    .map(
      (i) => `<div class="history-item">
        <small>${escapeHtml(i.provider)} &middot; ${escapeHtml(i.script)} &middot; ${escapeHtml(new Date(i.created_at).toLocaleString())}</small>
        <p style="font-family:'${escapeHtml(i.font_family)}',sans-serif">${escapeHtml(i.text)}</p>
      </div>`
    )
    .join("");
}

async function loadHistory() {
  try {
    const r = await fetch("/history");
    const data = await r.json();
    if (!r.ok) throw new Error(data.error);
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
    const r = await fetch("/transcribe", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error);

    ensureFont(data.font_family, data.font_url);
    transcript.textContent = data.text;
    transcript.style.fontFamily = `"${data.font_family}", sans-serif`;
    status.textContent = "Done.";
    await loadHistory();
  } catch (e) {
    transcript.textContent = "Transcription failed.";
    status.textContent = e.message;
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
loadHistory();
