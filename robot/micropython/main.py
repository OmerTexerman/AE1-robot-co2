try:
    import socket
except ImportError:
    socket = None

import time
import ujson
import ubinascii
import urandom
import uselect
from machine import unique_id

try:
    import network
except ImportError:
    network = None

try:
    import secrets
except ImportError:
    raise RuntimeError("Copy secrets.example.py to secrets.py and fill in the robot settings.")

try:
    from boot import cdc_data
except Exception:
    cdc_data = None

import pins
import motion as motion_module
from motion import (
    Motion, MotionError,
    STATUS_IDLE, STATUS_RUNNING, STATUS_COMPLETE, STATUS_FAILED, STATUS_ABORTED,
)


STATE_PATH = "pairing_state.json"
LAST_RENDER_PATH = "last_render.json"
BUFFER_SIZE = 4096
SERIAL_BUF_MAX = 4096
SERIAL_FRAME_PREFIX = b"AE1 "
SERIAL_FRAME_HEADER_MAX = 32
SERIAL_MESSAGE_MAX = 131072
DISCOVERY_MAGIC = b"AE1_DISCOVERY_V1"
CLIENT_TIMEOUT_SECONDS = 3
MAX_OPERATIONS = 5000
MAX_POINTS_PER_OP = 2000

_state_cache = None
_motion = None
_pending_job = None


def log(message):
    print("[robot] {}".format(message))


def load_json(path, default):
    try:
        with open(path, "r") as handle:
            return ujson.load(handle)
    except OSError:
        return default
    except ValueError:
        return default


def save_json(path, payload):
    with open(path, "w") as handle:
        ujson.dump(payload, handle)


def load_state():
    global _state_cache
    if _state_cache is None:
        _state_cache = load_json(STATE_PATH, {})
    return _state_cache


def save_state(state):
    global _state_cache
    save_json(STATE_PATH, state)
    _state_cache = state


DEVICE_ID = ubinascii.hexlify(unique_id()).decode()


def device_id():
    return DEVICE_ID


def make_token():
    return "{:08x}{:08x}".format(urandom.getrandbits(32), urandom.getrandbits(32))


def make_job_id(prefix):
    return "{}-{}-{:04x}".format(prefix, int(time.time()), urandom.getrandbits(16))


def send_all(client, payload):
    view = memoryview(payload)
    total_sent = 0

    while total_sent < len(payload):
        sent = client.send(view[total_sent:])
        if sent is None:
            sent = len(view[total_sent:])
        if sent <= 0:
            raise OSError("socket write failed")
        total_sent += sent


def json_response(client, status_code, payload):
    body = ujson.dumps(payload).encode()
    reason = "OK" if status_code < 400 else "ERROR"
    headers = [
        "HTTP/1.1 {} {}".format(status_code, reason),
        "Content-Type: application/json",
        "Content-Length: {}".format(len(body)),
        "Connection: close",
        "",
        "",
    ]
    send_all(client, "\r\n".join(headers).encode() + body)


def error_response(client, status_code, message):
    json_response(client, status_code, {"error": message})


def parse_request(client):
    data = bytearray()
    while b"\r\n\r\n" not in data and len(data) < BUFFER_SIZE:
        try:
            chunk = client.recv(512)
        except OSError as exc:
            raise ValueError("socket read failed: {}".format(exc))
        if not chunk:
            raise ValueError("client disconnected before request headers completed")
        data.extend(chunk)

    if b"\r\n\r\n" not in data:
        raise ValueError("request headers too large or incomplete")

    header_blob, _, body = bytes(data).partition(b"\r\n\r\n")
    header_lines = header_blob.decode().split("\r\n")
    try:
        method, path, _ = header_lines[0].split(" ", 2)
    except ValueError:
        raise ValueError("malformed request line")
    headers = {}

    for line in header_lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    try:
        content_length = int(headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("invalid content length")
    if len(body) < content_length:
        body_buf = bytearray(body)
        while len(body_buf) < content_length:
            try:
                chunk = client.recv(min(512, content_length - len(body_buf)))
            except OSError as exc:
                raise ValueError("socket body read failed: {}".format(exc))
            if not chunk:
                raise ValueError("client disconnected before request body completed")
            body_buf.extend(chunk)
        body = bytes(body_buf)

    payload = {}
    if content_length:
        try:
            payload = ujson.loads(body.decode())
        except ValueError:
            raise ValueError("invalid json body")
        if not isinstance(payload, dict):
            raise ValueError("json body must be an object")

    qs = ""
    if "?" in path:
        path, _, qs = path.partition("?")

    return method, path, qs, headers, payload


def parse_query(qs):
    params = {}
    if not qs:
        return params
    for chunk in qs.split("&"):
        if "=" in chunk:
            k, _, v = chunk.partition("=")
            params[k] = v
        else:
            params[chunk] = ""
    return params


def require_token(headers, state):
    return headers.get("x-pair-token") == state.get("pair_token")


def hello_payload(ip_address, state):
    payload = {
        "device_name": secrets.DEVICE_NAME,
        "device_id": device_id(),
        "ip_address": ip_address,
        "listen_port": secrets.LISTEN_PORT,
        "paired": bool(state.get("pair_token")),
        "serial_framing": True,
    }
    if _motion is not None:
        payload["steps_per_mm"] = pins.STEPS_PER_MM
        payload["calibrated"] = _motion.calibrated
        if _motion.calibrated:
            payload["work_area_mm"] = [_motion.work_area_x_mm, _motion.work_area_y_mm]
    return payload


def _set_pending_job(action, payload, kind):
    """Reserve the motion controller for a new action. Returns (job_id, error_message).
    error_message is non-None on rejection (busy, validation failed, etc)."""
    global _pending_job
    if _motion is None:
        return None, "motion controller unavailable"
    status = _motion.get_status()["status"]
    if status == STATUS_RUNNING or _pending_job is not None:
        return None, "robot is busy"
    if not _motion.calibrated and kind not in ("home", "calibrate"):
        return None, "robot is not calibrated — run /calibrate first"

    job_id = make_job_id(kind)
    # Let /job reflect the queued state immediately.
    js = _motion._job_state
    js["status"] = "queued"
    js["kind"] = kind
    js["job_id"] = job_id
    js["op_index"] = 0
    js["total_ops"] = 0
    js["error"] = None
    js["result"] = None

    _pending_job = {"kind": kind, "job_id": job_id, "payload": payload}
    return job_id, None


def _pen_motion_error():
    if _motion is None:
        return "motion controller unavailable"
    status = _motion.get_status()["status"]
    if status in (STATUS_RUNNING, "queued") or _pending_job is not None:
        return "pen control unavailable while motion is active"
    return None


def _validate_render_payload(payload):
    """Validate operations from a /render payload. Returns (operations, error)."""
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return None, "operations must be a list"
    if len(operations) == 0:
        return None, "operations is empty"
    if len(operations) > MAX_OPERATIONS:
        return None, "too many operations: {} (max {})".format(
            len(operations), MAX_OPERATIONS)

    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            return None, "operation {} is not an object".format(i)
        op_type = op.get("type")
        if op_type == "draw":
            pts = op.get("points")
            if not isinstance(pts, list) or len(pts) < 2:
                return None, "operation {} (draw): needs at least 2 points".format(i)
            if len(pts) > MAX_POINTS_PER_OP:
                return None, "operation {}: too many points ({} > {})".format(
                    i, len(pts), MAX_POINTS_PER_OP)
            for j, pt in enumerate(pts):
                err = _validate_render_point(pt, "operation {} point {}".format(i, j))
                if err:
                    return None, err
        elif op_type == "travel":
            pts = op.get("points")
            if not isinstance(pts, list) or len(pts) < 1:
                return None, "operation {} (travel): needs at least 1 point".format(i)
            if len(pts) > MAX_POINTS_PER_OP:
                return None, "operation {}: too many points ({} > {})".format(
                    i, len(pts), MAX_POINTS_PER_OP)
            for j, pt in enumerate(pts):
                err = _validate_render_point(pt, "operation {} point {}".format(i, j))
                if err:
                    return None, err
        elif op_type == "punch":
            pt = op.get("point")
            err = _validate_render_point(pt, "operation {} point".format(i))
            if err:
                return None, err
        else:
            return None, "operation {}: unknown type {}".format(i, op_type)

    return operations, None


def _validate_render_point(point, label):
    if not isinstance(point, list) or len(point) != 2:
        return "{} must contain exactly 2 coordinates".format(label)
    if _render_coord_invalid(point[0]) or _render_coord_invalid(point[1]):
        return "{} coordinates must be numbers".format(label)
    return None


def _render_coord_invalid(value):
    return isinstance(value, bool) or not isinstance(value, (int, float))


def dispatch_request(method, path, qs, headers, payload, ip_address, skip_auth=False):
    state = load_state()
    log("request method={} path={} skip_auth={}".format(method, path, skip_auth))

    if method == "GET" and path == "/hello":
        return 200, hello_payload(ip_address, state)

    if method == "POST" and path == "/pair":
        if payload.get("pairing_code") != secrets.PAIRING_CODE:
            log("pair rejected reason=incorrect_code")
            return 403, {"error": "Incorrect pairing code."}

        state = {
            "pair_token": make_token(),
            "paired_client": payload.get("client_name", "speech-app"),
            "paired_at": time.time(),
        }
        save_state(state)
        log("pair accepted client={} token={}...".format(state["paired_client"], state["pair_token"][:8]))
        return 200, {
            "device_name": secrets.DEVICE_NAME,
            "device_id": device_id(),
            "pair_token": state["pair_token"],
            "paired_client": state["paired_client"],
        }

    if not skip_auth and not require_token(headers, state):
        return 401, {"error": "Missing or invalid pair token."}

    if method == "GET" and path == "/status":
        last_render = load_json(LAST_RENDER_PATH, {})
        body = {
            "device_name": secrets.DEVICE_NAME,
            "device_id": device_id(),
            "paired_client": state.get("paired_client"),
            "last_render": last_render,
        }
        if _motion is not None:
            body["motion"] = _motion.get_status()
            if _motion.calibrated:
                body["work_area_mm"] = [_motion.work_area_x_mm, _motion.work_area_y_mm]
        return 200, body

    if method == "POST" and path == "/unpair":
        save_state({})
        log("unpair completed")
        return 200, {"ok": True}

    if method == "GET" and path == "/job":
        if _motion is None:
            return 503, {"error": "motion not initialized"}
        return 200, _motion.get_status()

    if method == "POST" and path == "/job/abort":
        if _motion is None:
            return 503, {"error": "motion not initialized"}
        _motion.request_abort()
        log("abort requested")
        return 200, {"aborted": True}

    if method == "POST" and path == "/home":
        job_id, err = _set_pending_job("home", {}, "home")
        if err:
            return 409, {"error": err}
        log("home queued job_id={}".format(job_id))
        return 202, {"accepted": True, "job_id": job_id, "kind": "home"}

    if method == "POST" and path == "/calibrate":
        job_id, err = _set_pending_job("calibrate", {}, "calibrate")
        if err:
            return 409, {"error": err}
        log("calibrate queued job_id={}".format(job_id))
        return 202, {"accepted": True, "job_id": job_id, "kind": "calibrate"}

    if method == "POST" and path == "/jog":
        try:
            dx = float(payload.get("dx", 0))
            dy = float(payload.get("dy", 0))
        except (TypeError, ValueError):
            return 400, {"error": "dx and dy must be numbers"}
        job_id, err = _set_pending_job("jog", {"dx": dx, "dy": dy}, "jog")
        if err:
            return 409, {"error": err}
        log("jog queued dx={} dy={} job_id={}".format(dx, dy, job_id))
        return 202, {"accepted": True, "job_id": job_id, "kind": "jog"}

    if method == "POST" and path == "/move":
        try:
            x = float(payload.get("x"))
            y = float(payload.get("y"))
        except (TypeError, ValueError):
            return 400, {"error": "x and y must be numbers"}
        job_id, err = _set_pending_job("move", {"x": x, "y": y}, "move")
        if err:
            return 409, {"error": err}
        log("move queued x={} y={} job_id={}".format(x, y, job_id))
        return 202, {"accepted": True, "job_id": job_id, "kind": "move"}

    if method == "POST" and path == "/pen/up":
        err = _pen_motion_error()
        if err is not None:
            return 409, {"error": err}
        _motion.pen.up()
        return 200, {"pen": _motion.pen.state, "duty": _motion.pen.current_duty}

    if method == "POST" and path == "/pen/down":
        err = _pen_motion_error()
        if err is not None:
            return 409, {"error": err}
        _motion.pen.down()
        return 200, {"pen": _motion.pen.state, "duty": _motion.pen.current_duty}

    if method == "GET" and path == "/pen/config":
        if _motion is None:
            return 503, {"error": "motion controller unavailable"}
        return 200, {
            "min_duty": pins.SERVO_MIN_DUTY,
            "max_duty": pins.SERVO_MAX_DUTY,
            "pen_up_duty": _motion.pen.up_duty,
            "pen_down_duty": _motion.pen.down_duty,
            "punch_duty": _motion.pen.punch_duty,
            "state": _motion.pen.state,
            "current_duty": _motion.pen.current_duty,
        }

    if method == "POST" and path == "/pen/set":
        err = _pen_motion_error()
        if err is not None:
            return 409, {"error": err}
        try:
            duty = int(payload.get("duty", 0))
        except (TypeError, ValueError):
            return 400, {"error": "duty must be an integer"}
        if not (pins.SERVO_MIN_DUTY <= duty <= pins.SERVO_MAX_DUTY):
            return 400, {
                "error": "duty must be between {} and {}".format(
                    pins.SERVO_MIN_DUTY, pins.SERVO_MAX_DUTY,
                )
            }
        applied = _motion.pen.set_position(duty)
        return 200, {"pen": _motion.pen.state, "duty": applied}

    if method == "POST" and path == "/pen/idle":
        err = _pen_motion_error()
        if err is not None:
            return 409, {"error": err}
        _motion.pen.idle()
        return 200, {"pen": _motion.pen.state, "duty": _motion.pen.current_duty}

    if method == "POST" and path == "/pen/save":
        err = _pen_motion_error()
        if err is not None:
            return 409, {"error": err}
        if "pen_up_duty" in payload:
            try:
                up_duty = int(payload["pen_up_duty"])
            except (TypeError, ValueError):
                return 400, {"error": "pen_up_duty must be an integer"}
            if not (pins.SERVO_MIN_DUTY <= up_duty <= pins.SERVO_MAX_DUTY):
                return 400, {
                    "error": "pen_up_duty must be between {} and {}".format(
                        pins.SERVO_MIN_DUTY, pins.SERVO_MAX_DUTY,
                    )
                }
            _motion.pen.up_duty = up_duty
        if "pen_down_duty" in payload:
            try:
                down_duty = int(payload["pen_down_duty"])
            except (TypeError, ValueError):
                return 400, {"error": "pen_down_duty must be an integer"}
            if not (pins.SERVO_MIN_DUTY <= down_duty <= pins.SERVO_MAX_DUTY):
                return 400, {
                    "error": "pen_down_duty must be between {} and {}".format(
                        pins.SERVO_MIN_DUTY, pins.SERVO_MAX_DUTY,
                    )
                }
            _motion.pen.down_duty = down_duty
            if _motion.pen._punch_tracks_down and "punch_duty" not in payload:
                _motion.pen.punch_duty = down_duty
        if "punch_duty" in payload:
            try:
                punch_duty = int(payload["punch_duty"])
            except (TypeError, ValueError):
                return 400, {"error": "punch_duty must be an integer"}
            if not (pins.SERVO_MIN_DUTY <= punch_duty <= pins.SERVO_MAX_DUTY):
                return 400, {
                    "error": "punch_duty must be between {} and {}".format(
                        pins.SERVO_MIN_DUTY, pins.SERVO_MAX_DUTY,
                    )
                }
            _motion.pen.punch_duty = punch_duty
            _motion.pen._punch_tracks_down = False
        _motion.pen.save_config()
        log("pen config saved up={} down={} punch={}".format(
            _motion.pen.up_duty, _motion.pen.down_duty, _motion.pen.punch_duty,
        ))
        return 200, {
            "pen_up_duty": _motion.pen.up_duty,
            "pen_down_duty": _motion.pen.down_duty,
            "punch_duty": _motion.pen.punch_duty,
        }

    if method == "POST" and path == "/render":
        mode = payload.get("mode", "write")
        if "operations" not in payload:
            return 400, {"error": "Render requires 'operations' field. Update speech-app."}

        operations, err = _validate_render_payload(payload)
        if err:
            return 400, {"error": err}

        job_id, err = _set_pending_job("render", {
            "operations": operations,
            "mode": mode,
        }, "render")
        if err:
            return 409, {"error": err}

        save_json(LAST_RENDER_PATH, {
            "job_id": job_id,
            "mode": mode,
            "submitted_at": payload.get("submitted_at"),
            "received_at": time.time(),
            "operation_count": len(operations),
        })
        log("render queued job_id={} ops={}".format(job_id, len(operations)))
        return 202, {"accepted": True, "job_id": job_id, "kind": "render",
                     "operation_count": len(operations)}

    log("request not found path={}".format(path))
    return 404, {"error": "Not found."}


def handle_request(client, ip_address):
    try:
        method, path, qs, headers, payload = parse_request(client)
    except ValueError as exc:
        log("request parse failed error={}".format(exc))
        error_response(client, 400, "Bad request: {}".format(exc))
        return

    try:
        status_code, response_body = dispatch_request(method, path, qs, headers, payload, ip_address)
    except Exception as exc:
        log("dispatch crashed error={}".format(exc))
        error_response(client, 500, "Robot server error: {}".format(exc))
        return

    json_response(client, status_code, response_body)


def serial_write(cdc, data):
    """Write all bytes to the CDC data channel. MicroPython's CDCInterface
    has a small internal buffer (~256 bytes). A single .write() of a large
    payload silently truncates. We chunk the write and yield between chunks
    so the USB stack can flush each one to the host."""
    try:
        mv = memoryview(data)
        offset = 0
        while offset < len(data):
            chunk = mv[offset:offset + 128]
            n = cdc.write(chunk)
            if n is None:
                n = len(chunk)
            offset += n
            if offset < len(data):
                time.sleep_ms(2)
    except Exception as exc:
        log("serial write error={}".format(exc))


def serial_write_response(cdc, payload, framed=False):
    body = ujson.dumps(payload).encode()
    if framed:
        header = SERIAL_FRAME_PREFIX + str(len(body)).encode() + b"\n"
        serial_write(cdc, header + body)
    else:
        serial_write(cdc, body + b"\n")


def handle_serial_command(cdc, message, ip_address, framed=False):
    try:
        cmd = ujson.loads(message)
    except ValueError:
        serial_write_response(cdc, {"status": 400, "body": {"error": "Invalid JSON"}}, framed=framed)
        return
    if not isinstance(cmd, dict):
        serial_write_response(cdc, {"status": 400, "body": {"error": "JSON command must be an object"}}, framed=framed)
        return

    raw_method = cmd.get("method", "GET")
    raw_path = cmd.get("path", "/")
    headers = cmd.get("headers", {})
    payload = cmd.get("body", {})
    if not isinstance(raw_method, str):
        serial_write_response(cdc, {"status": 400, "body": {"error": "method must be a string"}}, framed=framed)
        return
    if not isinstance(raw_path, str):
        serial_write_response(cdc, {"status": 400, "body": {"error": "path must be a string"}}, framed=framed)
        return
    if not isinstance(headers, dict):
        serial_write_response(cdc, {"status": 400, "body": {"error": "headers must be an object"}}, framed=framed)
        return
    if not isinstance(payload, dict):
        serial_write_response(cdc, {"status": 400, "body": {"error": "body must be an object"}}, framed=framed)
        return

    method = raw_method.upper()
    qs = ""
    path = raw_path
    if "?" in raw_path:
        path, _, qs = raw_path.partition("?")

    try:
        status_code, response_body = dispatch_request(
            method, path, qs, headers, payload, ip_address, skip_auth=True
        )
    except Exception as exc:
        log("serial dispatch crashed error={}".format(exc))
        status_code = 500
        response_body = {"error": "Robot server error: {}".format(exc)}

    serial_write_response(cdc, {"status": status_code, "body": response_body}, framed=framed)


def handle_discovery(discovery_socket, ip_address):
    try:
        payload, address = discovery_socket.recvfrom(256)
    except OSError:
        return

    if payload != DISCOVERY_MAGIC:
        return

    log("discovery reply sent to {}:{}".format(address[0], address[1]))
    response = ujson.dumps(hello_payload(ip_address, load_state()))
    discovery_socket.sendto(response.encode(), address)


def drain_serial(cdc, serial_buf, ip_address):
    chunk = cdc.read(-1)
    if not chunk:
        return serial_buf

    serial_buf.extend(chunk)
    while True:
        if serial_buf.startswith(SERIAL_FRAME_PREFIX):
            nl = serial_buf.find(b"\n")
            if nl < 0:
                if len(serial_buf) > SERIAL_FRAME_HEADER_MAX:
                    log("serial frame header too large, discarding {} bytes".format(len(serial_buf)))
                    serial_buf[:] = b""
                break

            try:
                message_len = int(bytes(serial_buf[len(SERIAL_FRAME_PREFIX):nl]))
            except ValueError:
                log("serial frame header invalid, dropping {} bytes".format(nl + 1))
                serial_buf[:] = serial_buf[nl + 1:]
                continue

            if message_len < 0 or message_len > SERIAL_MESSAGE_MAX:
                log("serial frame rejected len={}".format(message_len))
                serial_buf[:] = b""
                break

            frame_end = nl + 1 + message_len
            if len(serial_buf) < frame_end:
                break

            message = bytes(serial_buf[nl + 1:frame_end])
            serial_buf[:] = serial_buf[frame_end:]
            try:
                handle_serial_command(cdc, message.decode(), ip_address, framed=True)
            except Exception as exc:
                log("serial command error={}".format(exc))
            continue

        nl = serial_buf.find(b"\n")
        if nl < 0:
            if len(serial_buf) > SERIAL_BUF_MAX:
                log("serial buffer overflow, discarding {} bytes".format(len(serial_buf)))
                serial_buf[:] = b""
            break
        line = bytes(serial_buf[:nl]).strip()
        serial_buf[:] = serial_buf[nl + 1:]
        if line:
            try:
                handle_serial_command(cdc, line.decode(), ip_address, framed=False)
            except Exception as exc:
                log("serial command error={}".format(exc))
    return serial_buf


def setup_wifi(serial_buf, cdc):
    ip_address = "0.0.0.0"
    if network is None or not hasattr(network, "WLAN") or not hasattr(network, "STA_IF"):
        log("Wi-Fi not supported on this board. USB serial only.")
        return None, ip_address, serial_buf

    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
    except Exception as exc:
        log("Wi-Fi unavailable: {}. USB serial only.".format(exc))
        return None, ip_address, serial_buf

    ssid = getattr(secrets, "WIFI_SSID", "")
    password = getattr(secrets, "WIFI_PASSWORD", "")
    if not ssid:
        log("Wi-Fi credentials not configured. USB serial only.")
        return wlan, ip_address, serial_buf

    if not wlan.isconnected():
        try:
            wlan.connect(ssid, password)
        except Exception as exc:
            log("Wi-Fi connect failed immediately: {}. USB serial only.".format(exc))
            return wlan, ip_address, serial_buf

    log("Waiting for Wi-Fi (serial is active)...")
    for _ in range(60):
        if wlan.isconnected():
            break
        time.sleep(0.5)
        if cdc is not None:
            serial_buf = drain_serial(cdc, serial_buf, ip_address)
        # Allow the first USB-queued job to start during Wi-Fi setup instead
        # of sitting in "queued" until the 30 s wait finishes.
        if _pending_job is not None and _motion is not None:
            _run_pending_job()

    if wlan.isconnected():
        ip_address = wlan.ifconfig()[0]
        log("Robot Wi-Fi ready at http://{}:{}".format(ip_address, secrets.LISTEN_PORT))
    else:
        log("Wi-Fi connection failed. Continuing with USB serial only.")

    return wlan, ip_address, serial_buf


def setup_network_servers(poller):
    tcp_server = None
    udp_server = None
    if socket is None:
        log("socket module unavailable — no TCP/UDP. USB serial only.")
        return tcp_server, udp_server
    try:
        tcp_address = socket.getaddrinfo("0.0.0.0", secrets.LISTEN_PORT)[0][-1]
        tcp_server = socket.socket()
        tcp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_server.bind(tcp_address)
        tcp_server.listen(1)
        tcp_server.setblocking(False)

        discovery_port = getattr(secrets, "DISCOVERY_PORT", 9090)
        udp_address = socket.getaddrinfo("0.0.0.0", discovery_port)[0][-1]
        udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_server.bind(udp_address)
        udp_server.setblocking(False)

        poller.register(tcp_server, uselect.POLLIN)
        poller.register(udp_server, uselect.POLLIN)
        return tcp_server, udp_server
    except Exception as exc:
        log("Network services unavailable: {}. USB serial only.".format(exc))
        try:
            tcp_server.close()
        except Exception:
            pass
        try:
            udp_server.close()
        except Exception:
            pass
        return None, None


def _run_pending_job():
    """Pop _pending_job and execute it through _motion. Updates job_state.
    Returns True if a job was run, False otherwise."""
    global _pending_job
    if _pending_job is None or _motion is None:
        return False

    job = _pending_job
    _pending_job = None

    kind = job["kind"]
    job_id = job["job_id"]
    payload = job["payload"]

    js = _motion._job_state
    js["status"] = STATUS_RUNNING
    js["kind"] = kind
    js["job_id"] = job_id
    js["error"] = None
    js["result"] = None
    if _motion._abort_requested:
        js["status"] = STATUS_ABORTED
        _motion._abort_requested = False
        log("job aborted before start kind={} job_id={}".format(kind, job_id))
        return True
    _motion._abort_requested = False

    try:
        if kind == "home":
            _motion.home()
            js["status"] = STATUS_COMPLETE
            log("home complete job_id={}".format(job_id))

        elif kind == "calibrate":
            result = _motion.calibrate_sweep()
            js["result"] = result
            js["status"] = STATUS_COMPLETE
            log("calibrate complete travel_x_mm={} travel_y_mm={}".format(
                result["travel_x_mm"], result["travel_y_mm"]))

        elif kind == "jog":
            if not _motion.homed:
                log("auto-home before jog job_id={}".format(job_id))
                _motion.home()
            _motion.move_by_mm(payload["dx"], payload["dy"])
            js["status"] = STATUS_COMPLETE
            log("jog complete dx={} dy={}".format(payload["dx"], payload["dy"]))

        elif kind == "move":
            if not _motion.homed:
                log("auto-home before move job_id={}".format(job_id))
                _motion.home()
            _motion.move_to_mm(payload["x"], payload["y"])
            js["status"] = STATUS_COMPLETE
            log("move complete x={} y={}".format(payload["x"], payload["y"]))

        elif kind == "render":
            log("home before render job_id={}".format(job_id))
            _motion.home()
            _motion.execute_operations(payload["operations"], job_id=job_id)
            js["status"] = STATUS_RUNNING
            _motion.home()
            js["status"] = STATUS_COMPLETE
            log("render complete job_id={}".format(job_id))

        else:
            js["status"] = STATUS_FAILED
            js["error"] = "unknown job kind: {}".format(kind)

    except MotionError as exc:
        if js["status"] == STATUS_RUNNING:
            if _motion._abort_requested:
                js["status"] = STATUS_ABORTED
            else:
                js["status"] = STATUS_FAILED
                js["error"] = str(exc)
        log("job failed kind={} error={}".format(kind, exc))
    except Exception as exc:
        js["status"] = STATUS_FAILED
        js["error"] = "internal error"
        log("job crashed kind={} error={}".format(kind, exc))
        try:
            _motion.pen.up()
        except Exception:
            pass

    return True


def serve():
    global _motion

    serial_buf = bytearray()
    ip_address = "0.0.0.0"

    poller = uselect.poll()
    tcp_server = None
    udp_server = None

    if cdc_data is not None:
        log("CDC data channel available")

    # Create motion controller BEFORE WiFi setup so serial commands that
    # arrive during the WiFi wait (up to 30 s) already see _motion.
    _motion = Motion()
    if _motion.calibrated:
        log("motion controller ready: work_area={}x{}mm steps_per_mm={}".format(
            round(_motion.work_area_x_mm, 1), round(_motion.work_area_y_mm, 1), pins.STEPS_PER_MM))
    else:
        log("motion controller ready: NOT CALIBRATED — run /calibrate before sending jobs")

    wlan, ip_address, serial_buf = setup_wifi(serial_buf, cdc_data)

    log("Pairing code: {}".format(secrets.PAIRING_CODE))

    if wlan is not None and wlan.isconnected():
        tcp_server, udp_server = setup_network_servers(poller)

    # During motion this stays non-blocking; when idle it can block in poll().
    def service_io(poll_timeout_ms=0):
        nonlocal serial_buf
        try:
            events = poller.poll(poll_timeout_ms)
        except OSError:
            events = []
        for sock, _ev in events:
            if tcp_server is not None and sock is tcp_server:
                try:
                    client, _addr = tcp_server.accept()
                except OSError:
                    continue
                client.setblocking(True)
                client.settimeout(CLIENT_TIMEOUT_SECONDS)
                try:
                    handle_request(client, ip_address)
                except Exception as exc:
                    log("request crashed error={}".format(exc))
                    try:
                        json_response(client, 500, {"error": "Robot server error: {}".format(exc)})
                    except Exception:
                        pass
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass
            elif udp_server is not None and sock is udp_server:
                handle_discovery(udp_server, ip_address)
        if cdc_data is not None:
            serial_buf = drain_serial(cdc_data, serial_buf, ip_address)

    # Now that service_io is defined, give it to motion as the yield callback
    # so the server stays responsive during long moves.
    _motion._on_yield = lambda: service_io(0)
    log("serve loop starting")

    while True:
        if _pending_job is not None:
            _run_pending_job()
        else:
            service_io(1000)


serve()
