import tempfile
from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from font_selector import build_google_fonts_url, choose_font
from history_store import init_db, list_transcripts, save_transcript
from robot_client import (
    RobotClientError,
    discover_robots,
    fetch_status,
    pair_robot,
    send_render_job,
    unpair_robot,
)
from robot_store import clear_robot, load_robot, save_robot
from transcription import normalize_provider, transcribe_audio

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
init_db()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/history")
def history():
    items = list_transcripts()
    for item in items:
        item["font_url"] = build_google_fonts_url(item["font_family"])
    return jsonify({"items": items})


def serialize_robot_config(config: dict | None) -> dict | None:
    if not config:
        return None

    return {
        "base_url": config["base_url"],
        "host": config["host"],
        "port": config["port"],
        "device_name": config["device_name"],
        "device_id": config["device_id"],
        "client_name": config["client_name"],
        "paired_at": config["paired_at"],
    }


@app.get("/robot")
def robot_state():
    config = load_robot()
    if not config:
        app.logger.info("robot_state requested with no paired robot")
        return jsonify({"paired": False, "robot": None})

    try:
        status = fetch_status(config)
        connected = True
        error = None
        app.logger.info(
            "robot_state ok device=%s host=%s port=%s",
            config["device_name"],
            config["host"],
            config["port"],
        )
    except RobotClientError as exc:
        status = None
        connected = False
        error = str(exc)
        app.logger.warning(
            "robot_state failed device=%s host=%s port=%s error=%s",
            config["device_name"],
            config["host"],
            config["port"],
            exc,
        )

    return jsonify(
        {
            "paired": True,
            "robot": serialize_robot_config(config),
            "connected": connected,
            "status": status,
            "error": error,
        }
    )


@app.post("/robot/discover")
def robot_discover():
    try:
        robots = discover_robots()
    except OSError as exc:
        app.logger.exception("robot_discover failed: %s", exc)
        return (
            jsonify(
                {
                    "error": (
                        "Robot discovery failed. If the speech app is in Docker, run it with host "
                        f"networking for hotspot discovery. {exc}"
                    )
                }
            ),
            502,
        )

    app.logger.info("robot_discover completed count=%s robots=%s", len(robots), robots)
    return jsonify({"items": robots, "count": len(robots)})


@app.post("/robot/pair")
def robot_pair():
    payload = request.get_json(silent=True) or {}
    host = str(payload.get("host", "")).strip()
    pairing_code = str(payload.get("pairing_code", "")).strip()
    client_name = str(payload.get("client_name", "speech-app")).strip() or "speech-app"

    try:
        port = int(payload.get("port", 8080))
    except (TypeError, ValueError):
        return jsonify({"error": "Robot port must be a number."}), 400

    if not host:
        return jsonify({"error": "Robot host or IP is required."}), 400
    if not pairing_code:
        return jsonify({"error": "Pairing code is required."}), 400

    app.logger.info("robot_pair requested host=%s port=%s client_name=%s", host, port, client_name)
    try:
        config = pair_robot(host=host, port=port, pairing_code=pairing_code, client_name=client_name)
        status = fetch_status(config)
    except RobotClientError as exc:
        app.logger.warning("robot_pair failed host=%s port=%s error=%s", host, port, exc)
        return jsonify({"error": str(exc)}), 502

    save_robot(config)
    app.logger.info(
        "robot_pair succeeded device=%s device_id=%s host=%s port=%s client_name=%s",
        config["device_name"],
        config["device_id"],
        config["host"],
        config["port"],
        config["client_name"],
    )
    return jsonify(
        {
            "paired": True,
            "robot": serialize_robot_config(config),
            "connected": True,
            "status": status,
        }
    )


@app.post("/robot/unpair")
def robot_unpair():
    config = load_robot()
    if not config:
        app.logger.info("robot_unpair requested with no paired robot")
        return jsonify({"paired": False, "robot": None})

    remote_error = None
    try:
        unpair_robot(config)
    except RobotClientError as exc:
        remote_error = str(exc)
        app.logger.warning(
            "robot_unpair remote warning device=%s host=%s port=%s error=%s",
            config["device_name"],
            config["host"],
            config["port"],
            exc,
        )

    clear_robot()
    app.logger.info(
        "robot_unpair completed device=%s host=%s port=%s",
        config["device_name"],
        config["host"],
        config["port"],
    )
    return jsonify({"paired": False, "robot": None, "warning": remote_error})


@app.post("/robot/render")
def robot_render():
    config = load_robot()
    if not config:
        return jsonify({"error": "No robot is paired."}), 400

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    font_family = str(payload.get("font_family", "")).strip() or "Noto Sans"
    script = str(payload.get("script", "")).strip() or "latin"

    if not text:
        return jsonify({"error": "Text is required before sending to the robot."}), 400

    app.logger.info(
        "robot_render requested device=%s host=%s port=%s chars=%s font=%s script=%s",
        config["device_name"],
        config["host"],
        config["port"],
        len(text),
        font_family,
        script,
    )
    try:
        result = send_render_job(config, text=text, font_family=font_family, script=script)
    except RobotClientError as exc:
        app.logger.warning(
            "robot_render failed device=%s host=%s port=%s error=%s",
            config["device_name"],
            config["host"],
            config["port"],
            exc,
        )
        return jsonify({"error": str(exc)}), 502

    app.logger.info(
        "robot_render accepted device=%s host=%s port=%s job_id=%s",
        config["device_name"],
        config["host"],
        config["port"],
        result.get("job_id"),
    )
    return jsonify(result)


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
    app.logger.info(
        "transcribe requested filename=%s suffix=%s provider=%s",
        audio.filename,
        suffix,
        provider,
    )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        audio.save(tmp_file)
        temp_path = Path(tmp_file.name)

    try:
        transcription = transcribe_audio(temp_path, provider)
    except Exception as exc:
        app.logger.exception("transcribe failed filename=%s provider=%s error=%s", audio.filename, provider, exc)
        return jsonify({"error": f"Transcription failed: {exc}"}), 500
    finally:
        temp_path.unlink(missing_ok=True)

    text = transcription["text"]
    if not text:
        return jsonify({"error": "The transcription service returned empty text."}), 500

    language = str(transcription.get("language") or "")
    font = choose_font(text, language)
    created_at = datetime.now(timezone.utc).isoformat()
    transcript_id = save_transcript(
        text=text,
        script=font["script"],
        font_family=font["font_family"],
        provider=transcription["provider"],
        language=language,
        created_at=created_at,
    )
    app.logger.info(
        "transcribe completed transcript_id=%s provider=%s chars=%s script=%s font=%s language=%s",
        transcript_id,
        transcription["provider"],
        len(text),
        font["script"],
        font["font_family"],
        language,
    )

    return jsonify(
        {
            "id": transcript_id,
            "text": text,
            "script": font["script"],
            "font_family": font["font_family"],
            "font_url": font["font_url"],
            "provider": transcription["provider"],
            "language": language,
            "language_confidence": transcription.get("language_confidence"),
            "created_at": created_at,
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(debug=True, host="0.0.0.0", port=port)
