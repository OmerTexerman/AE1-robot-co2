import tempfile
from datetime import datetime, timezone
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from db import init_db, list_transcripts, save_transcript
from font_selector import build_google_fonts_url, choose_font
from robot_client import RobotClientError
from robot_service import (
    discover_available_robots,
    get_current_robot,
    get_robot_connection_state,
    init_robot_session,
    paired_robot_payload,
    pair_with_robot,
    render_on_robot,
    set_current_robot,
    unpaired_robot_payload,
    unpair_current_robot,
)
from transcription import normalize_provider, transcribe_audio

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
init_robot_session(app)
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


def request_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def parse_port(value: object, error_message: str, default: int = 8080) -> int:
    if value in (None, ""):
        return default

    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc

    if not 1 <= port <= 65535:
        raise ValueError(error_message)

    return port


def parse_candidate_ports(raw_ports: object) -> list[int]:
    if raw_ports is None:
        return []
    if not isinstance(raw_ports, list):
        raise ValueError("Robot discovery ports must be a list.")

    candidate_ports: list[int] = []
    for raw_port in raw_ports:
        port = parse_port(raw_port, f"Invalid robot discovery port '{raw_port}'.")
        if port not in candidate_ports:
            candidate_ports.append(port)

    return candidate_ports


def parse_pairing_request(payload: dict) -> tuple[str, int, str, str]:
    host = str(payload.get("host", "")).strip()
    pairing_code = str(payload.get("pairing_code", "")).strip()
    client_name = str(payload.get("client_name", "speech-app")).strip() or "speech-app"
    port = parse_port(payload.get("port"), "Robot port must be a number.")

    if not host:
        raise ValueError("Robot host or IP is required.")
    if not pairing_code:
        raise ValueError("Pairing code is required.")

    return host, port, pairing_code, client_name


def parse_render_request(payload: dict) -> tuple[str, str, str]:
    text = str(payload.get("text", "")).strip()
    font_family = str(payload.get("font_family", "")).strip() or "Noto Sans"
    script = str(payload.get("script", "")).strip() or "latin"

    if not text:
        raise ValueError("Text is required before sending to the robot.")

    return text, font_family, script


def save_uploaded_audio(audio) -> Path:
    suffix = Path(audio.filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        audio.save(tmp_file)
        return Path(tmp_file.name)


def build_transcription_response(
    transcription: dict,
    font: dict[str, str],
    created_at: str,
    transcript_id: int,
) -> dict:
    return {
        "id": transcript_id,
        "text": transcription["text"],
        "script": font["script"],
        "font_family": font["font_family"],
        "font_url": font["font_url"],
        "provider": transcription["provider"],
        "language": str(transcription.get("language") or ""),
        "language_confidence": transcription.get("language_confidence"),
        "created_at": created_at,
    }


@app.get("/robot")
def robot_state():
    config = get_current_robot(app)
    if not config:
        app.logger.info("robot_state requested with no paired robot")
        return jsonify(unpaired_robot_payload())

    return jsonify(paired_robot_payload(config, **get_robot_connection_state(app.logger, config)))


@app.post("/robot/discover")
def robot_discover():
    try:
        candidate_ports = parse_candidate_ports(request_payload().get("ports", []))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    current_robot = get_current_robot(app)
    if current_robot and current_robot["port"] not in candidate_ports:
        candidate_ports.append(int(current_robot["port"]))

    try:
        robots = discover_available_robots(candidate_ports)
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
    try:
        host, port, pairing_code, client_name = parse_pairing_request(request_payload())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    app.logger.info("robot_pair requested host=%s port=%s client_name=%s", host, port, client_name)
    try:
        config, status = pair_with_robot(host, port, pairing_code, client_name)
    except RobotClientError as exc:
        app.logger.warning("robot_pair failed host=%s port=%s error=%s", host, port, exc)
        return jsonify({"error": str(exc)}), 502

    set_current_robot(app, config)
    app.logger.info(
        "robot_pair succeeded device=%s device_id=%s host=%s port=%s client_name=%s",
        config["device_name"],
        config["device_id"],
        config["host"],
        config["port"],
        config["client_name"],
    )
    return jsonify(paired_robot_payload(config, connected=True, status=status))


@app.post("/robot/unpair")
def robot_unpair():
    config = get_current_robot(app)
    if not config:
        app.logger.info("robot_unpair requested with no paired robot")
        return jsonify(unpaired_robot_payload())

    remote_error = unpair_current_robot(config)
    if remote_error is not None:
        app.logger.warning(
            "robot_unpair remote warning device=%s host=%s port=%s error=%s",
            config["device_name"],
            config["host"],
            config["port"],
            remote_error,
        )

    set_current_robot(app, None)
    app.logger.info(
        "robot_unpair completed device=%s host=%s port=%s",
        config["device_name"],
        config["host"],
        config["port"],
    )
    return jsonify(unpaired_robot_payload(remote_error))


@app.post("/robot/render")
def robot_render():
    config = get_current_robot(app)
    if not config:
        return jsonify({"error": "No robot is paired."}), 400

    try:
        text, font_family, script = parse_render_request(request_payload())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

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
        result = render_on_robot(config, text, font_family, script)
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

    temp_path = save_uploaded_audio(audio)
    suffix = temp_path.suffix
    app.logger.info(
        "transcribe requested filename=%s suffix=%s provider=%s",
        audio.filename,
        suffix,
        provider,
    )

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
        build_transcription_response(transcription, font, created_at, transcript_id)
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").strip() == "1"
    app.run(debug=debug, use_reloader=debug, host="0.0.0.0", port=port)
