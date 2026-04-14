import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from braille_translator import available_grades, normalize_grade, translate_to_braille_text
from font_selector import choose_font
from google_fonts import get_fonts_for_subset, warm_cache
from paper_sizes import (
    DEFAULT_FONT_SIZE_MM,
    DEFAULT_MARGINS,
    DEFAULT_PEN_TIP_MM,
    GANTRY_HEIGHT_MM,
    GANTRY_WIDTH_MM,
    PAPER_OFFSET,
    list_paper_sizes,
)
from font_renderer import list_hershey_fonts
from toolpath import generate_braille_toolpath, generate_write_toolpath
from robot_client import (
    TRANSPORT_SERIAL,
    RobotClientError,
    close_transport,
    fetch_job_status,
    fetch_pen_config,
    send_abort_command,
    send_calibrate_command,
    send_home_command,
    send_jog_command,
    send_move_command,
    send_paths_job,
    send_pen_save,
    send_pen_set,
)
from robot_service import (
    discover_available_robots,
    get_current_robot,
    get_robot_connection_state,
    init_robot_session,
    paired_robot_payload,
    pair_with_robot,
    pair_with_robot_usb,
    set_current_robot,
    unpaired_robot_payload,
    unpair_current_robot,
)
from request_parsing import (
    DEFAULT_CLIENT_NAME,
    parse_float,
    parse_int,
    parse_optional_int,
    parse_pairing_request,
    parse_port,
    parse_string,
    parse_toolpath_mode,
    parse_toolpath_request,
    validate_operations,
)
from transcription import normalize_provider, transcribe_audio

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
init_robot_session(app)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)


@app.get("/")
def index():
    return render_template("index.html")


def request_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def parse_discovery_port(payload: dict) -> int:
    return parse_port(payload.get("port"), "Robot discovery port must be a number.")


def save_uploaded_audio(audio) -> Path:
    suffix = Path(audio.filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        audio.save(tmp_file)
        return Path(tmp_file.name)


def build_transcription_response(
    transcription: dict,
    font: dict[str, str],
    created_at: str,
) -> dict:
    language = str(transcription.get("language") or "")
    return {
        "text": transcription["text"],
        "script": font["script"],
        "font_family": font["font_family"],
        "font_url": font["font_url"],
        "provider": transcription["provider"],
        "language": language,
        "language_confidence": transcription.get("language_confidence"),
        "created_at": created_at,
        "available_grades": available_grades(language or "en"),
    }


def build_toolpath_from_payload(payload: dict[str, Any]) -> dict:
    request_data = parse_toolpath_request(payload)
    common_kwargs = {
        "paper_size": request_data["paper_size"],
        "margins": request_data["margins"],
        "paper_offset": request_data["paper_offset"],
    }

    if request_data["mode"] == "braille":
        return generate_braille_toolpath(
            request_data["text"],
            language=request_data["language"],
            grade=request_data["grade"],
            **common_kwargs,
        )

    return generate_write_toolpath(
        request_data["text"],
        request_data["font_family"],
        font_size_mm=request_data["font_size_mm"],
        pen_tip_mm=request_data["pen_tip_mm"],
        render_mode=request_data["render_mode"],
        **common_kwargs,
    )




@app.post("/braille/preview")
def braille_preview():
    payload = request_payload()
    try:
        text = parse_string(payload.get("text"), "Text", required=True)
        language = parse_string(payload.get("language"), "Language", default="en")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    grade = normalize_grade(payload.get("grade"))

    braille_text = translate_to_braille_text(text, language, grade)
    return jsonify({"braille_text": braille_text})


@app.get("/braille/grades")
def braille_grades():
    language = request.args.get("language", "").strip() or "en"
    grades = available_grades(language)
    return jsonify({"language": language, "grades": grades})


@app.get("/robot")
def robot_state():
    config = get_current_robot(app)
    if not config:
        app.logger.info("robot_state requested with no paired robot")
        return jsonify(unpaired_robot_payload())

    connection_state = get_robot_connection_state(app.logger, config)
    if connection_state.pop("disconnected", False):
        close_transport(config)
        set_current_robot(app, None)
        app.logger.info("robot auto-unpaired due to USB disconnect serial_port=%s", config.get("serial_port"))
        return jsonify(unpaired_robot_payload("USB robot disconnected."))

    return jsonify(paired_robot_payload(config, **connection_state))


@app.post("/robot/discover")
def robot_discover():
    try:
        discovery_port = parse_discovery_port(request_payload())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    current_robot = get_current_robot(app)
    try:
        robots = discover_available_robots(discovery_port, current_robot)
    except OSError as exc:
        app.logger.exception("robot_discover failed: %s", exc)
        return (
            jsonify(
                {
                        "error": (
                        "Robot discovery failed. If the speech app is in Docker, run it with host "
                        f"networking for local-network discovery. {exc}"
                        )
                }
            ),
            502,
        )

    app.logger.info("robot_discover completed count=%s robots=%s", len(robots), robots)
    return jsonify({"items": robots, "count": len(robots)})


@app.post("/robot/pair")
def robot_pair():
    payload = request_payload()

    if payload.get("transport") == TRANSPORT_SERIAL:
        try:
            serial_port = parse_string(payload.get("serial_port"), "Serial port", required=True)
            client_name = parse_string(payload.get("client_name"), "Client name", default=DEFAULT_CLIENT_NAME)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        app.logger.info("robot_pair_usb requested serial_port=%s client_name=%s", serial_port, client_name)
        try:
            config, connection_state = pair_with_robot_usb(app.logger, serial_port, client_name)
        except RobotClientError as exc:
            app.logger.warning("robot_pair_usb failed serial_port=%s error=%s", serial_port, exc)
            return jsonify({"error": str(exc)}), 502

        set_current_robot(app, config)
        return jsonify(paired_robot_payload(config, **connection_state))

    try:
        host, port, pairing_code, client_name = parse_pairing_request(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    app.logger.info("robot_pair requested host=%s port=%s client_name=%s", host, port, client_name)
    try:
        config, connection_state = pair_with_robot(app.logger, host, port, pairing_code, client_name)
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
    return jsonify(paired_robot_payload(config, **connection_state))


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

    payload = request_payload()

    # Accept either preview-generated operations or legacy toolpath params.
    operations = payload.get("operations")
    mode = payload.get("mode", "write")

    if operations is None:
        try:
            toolpath = build_toolpath_from_payload(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            app.logger.exception("robot_render toolpath generation failed: %s", exc)
            return jsonify({"error": f"Toolpath generation failed: {exc}"}), 500
        operations = toolpath.get("operations", [])
        mode = toolpath.get("mode", mode)

    try:
        mode = parse_toolpath_mode(mode)
        validate_operations(operations)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    app.logger.info(
        "robot_render device=%s host=%s port=%s ops=%s mode=%s",
        config["device_name"], config["host"], config["port"], len(operations), mode,
    )

    try:
        result = send_paths_job(config, operations=operations, mode=mode)
    except RobotClientError as exc:
        app.logger.warning(
            "robot_render failed device=%s host=%s port=%s error=%s",
            config["device_name"], config["host"], config["port"], exc,
        )
        return jsonify({"error": str(exc)}), 502

    app.logger.info(
        "robot_render accepted device=%s host=%s port=%s job_id=%s",
        config["device_name"], config["host"], config["port"], result.get("job_id"),
    )
    return jsonify(result)


def _require_paired_robot():
    config = get_current_robot(app)
    if not config:
        return None, (jsonify({"error": "No robot is paired."}), 400)
    return config, None


@app.post("/robot/home")
def robot_home():
    config, err = _require_paired_robot()
    if err:
        return err
    try:
        result = send_home_command(config)
    except RobotClientError as exc:
        app.logger.warning("robot_home failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    app.logger.info("robot_home accepted job_id=%s", result.get("job_id"))
    return jsonify(result)


@app.post("/robot/calibrate")
def robot_calibrate():
    config, err = _require_paired_robot()
    if err:
        return err
    try:
        result = send_calibrate_command(config)
    except RobotClientError as exc:
        app.logger.warning("robot_calibrate failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    app.logger.info("robot_calibrate accepted job_id=%s", result.get("job_id"))
    return jsonify(result)


@app.post("/robot/jog")
def robot_jog():
    config, err = _require_paired_robot()
    if err:
        return err
    payload = request_payload()
    try:
        dx = parse_float(payload.get("dx", 0), "dx and dy must be numbers.", default=0)
        dy = parse_float(payload.get("dy", 0), "dx and dy must be numbers.", default=0)
    except ValueError:
        return jsonify({"error": "dx and dy must be numbers."}), 400
    try:
        result = send_jog_command(config, dx, dy)
    except RobotClientError as exc:
        app.logger.warning("robot_jog failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.post("/robot/move")
def robot_move():
    config, err = _require_paired_robot()
    if err:
        return err
    payload = request_payload()
    try:
        x = parse_float(payload.get("x"), "x and y must be numbers.")
        y = parse_float(payload.get("y"), "x and y must be numbers.")
    except ValueError:
        return jsonify({"error": "x and y must be numbers."}), 400
    try:
        result = send_move_command(config, x, y)
    except RobotClientError as exc:
        app.logger.warning("robot_move failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.post("/robot/abort")
def robot_abort():
    config, err = _require_paired_robot()
    if err:
        return err
    try:
        result = send_abort_command(config)
    except RobotClientError as exc:
        app.logger.warning("robot_abort failed: %s", exc)
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.get("/robot/pen/config")
def robot_pen_config():
    config, err = _require_paired_robot()
    if err:
        return err
    try:
        return jsonify(fetch_pen_config(config))
    except RobotClientError as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/robot/pen/set")
def robot_pen_set():
    config, err = _require_paired_robot()
    if err:
        return err
    payload = request_payload()
    try:
        duty = parse_int(payload.get("duty", 0), "duty must be a number", default=0)
    except ValueError:
        return jsonify({"error": "duty must be a number"}), 400
    try:
        return jsonify(send_pen_set(config, duty))
    except RobotClientError as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/robot/pen/save")
def robot_pen_save():
    config, err = _require_paired_robot()
    if err:
        return err
    payload = request_payload()
    try:
        up = parse_optional_int(payload.get("pen_up_duty"), "duty values must be numbers")
        down = parse_optional_int(payload.get("pen_down_duty"), "duty values must be numbers")
        punch = parse_optional_int(payload.get("punch_duty"), "duty values must be numbers")
    except ValueError:
        return jsonify({"error": "duty values must be numbers"}), 400
    try:
        return jsonify(send_pen_save(config, pen_up_duty=up, pen_down_duty=down, punch_duty=punch))
    except RobotClientError as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/robot/job")
def robot_job():
    config, err = _require_paired_robot()
    if err:
        return err
    try:
        result = fetch_job_status(config)
    except RobotClientError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@app.get("/paper-sizes")
def paper_sizes():
    return jsonify({
        "sizes": list_paper_sizes(),
        "gantry": {"width": GANTRY_WIDTH_MM, "height": GANTRY_HEIGHT_MM},
        "defaults": {
            "font_size_mm": DEFAULT_FONT_SIZE_MM,
            "pen_tip_mm": DEFAULT_PEN_TIP_MM,
            "margins": DEFAULT_MARGINS,
            "paper_offset": PAPER_OFFSET,
        },
    })


@app.get("/hershey-fonts")
def hershey_fonts():
    return jsonify({"fonts": list_hershey_fonts()})


@app.post("/toolpath/preview")
def toolpath_preview():
    payload = request_payload()
    try:
        result = build_toolpath_from_payload(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("toolpath_preview failed: %s", exc)
        return jsonify({"error": f"Toolpath generation failed: {exc}"}), 500

    return jsonify(result)


@app.get("/fonts")
def fonts():
    subset = request.args.get("subset", "").strip()
    if not subset:
        return jsonify({"error": "subset query parameter is required."}), 400

    return jsonify({"subset": subset, "fonts": get_fonts_for_subset(subset)})


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
        return jsonify({"error": "No speech detected. Please try again."}), 422

    language = str(transcription.get("language") or "")
    font = choose_font(text)
    created_at = datetime.now(timezone.utc).isoformat()
    app.logger.info(
        "transcribe completed provider=%s chars=%s script=%s font=%s language=%s",
        transcription["provider"],
        len(text),
        font["script"],
        font["font_family"],
        language,
    )

    return jsonify(
        build_transcription_response(transcription, font, created_at)
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "").strip() == "1"
    threading.Thread(target=warm_cache, daemon=True).start()
    app.run(debug=debug, use_reloader=debug, host="0.0.0.0", port=port)
