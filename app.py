import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from font_selector import choose_font
from history_store import init_db, list_transcripts, save_transcript
from transcription import normalize_provider, transcribe_audio

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
init_db()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/history")
def history():
    items = list_transcripts()
    for item in items:
        item["font_url"] = choose_font(item["text"])["font_url"]
    return jsonify({"items": items})


@app.post("/transcribe")
def transcribe():
    audio = request.files.get("audio")
    if audio is None or not audio.filename:
        return jsonify({"error": "No audio file was uploaded."}), 400

    try:
        provider = normalize_provider(request.form.get("provider"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    suffix = Path(audio.filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        audio.save(tmp_file)
        temp_path = Path(tmp_file.name)

    try:
        transcription = transcribe_audio(temp_path, provider)
    except Exception as exc:
        return jsonify({"error": f"Transcription failed: {exc}"}), 500
    finally:
        temp_path.unlink(missing_ok=True)

    text = transcription["text"]
    if not text:
        return jsonify({"error": "The transcription service returned empty text."}), 500

    font = choose_font(text)
    created_at = datetime.now(timezone.utc).isoformat()
    transcript_id = save_transcript(
        text=text,
        script=font["script"],
        font_family=font["font_family"],
        provider=transcription["provider"],
        created_at=created_at,
    )

    return jsonify(
        {
            "id": transcript_id,
            "text": text,
            "script": font["script"],
            "font_family": font["font_family"],
            "font_url": font["font_url"],
            "provider": transcription["provider"],
            "created_at": created_at,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
