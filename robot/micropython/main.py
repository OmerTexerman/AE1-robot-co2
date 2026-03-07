import network
import socket
import time
import ujson
import ubinascii
import urandom
import uselect
from machine import unique_id

try:
    import secrets
except ImportError:
    raise RuntimeError("Copy secrets.example.py to secrets.py and fill in Wi-Fi settings.")

try:
    from boot import cdc_data
except Exception:
    cdc_data = None


STATE_PATH = "pairing_state.json"
LAST_RENDER_PATH = "last_render.json"
BUFFER_SIZE = 4096
SERIAL_BUF_MAX = 4096
DISCOVERY_MAGIC = b"AE1_DISCOVERY_V1"
CLIENT_TIMEOUT_SECONDS = 3

_state_cache = None


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
            payload = {}

    return method, path, headers, payload


def require_token(headers, state):
    return headers.get("x-pair-token") == state.get("pair_token")


def hello_payload(ip_address, state):
    return {
        "device_name": secrets.DEVICE_NAME,
        "device_id": device_id(),
        "ip_address": ip_address,
        "listen_port": secrets.LISTEN_PORT,
        "paired": bool(state.get("pair_token")),
    }


def dispatch_request(method, path, headers, payload, ip_address, skip_auth=False):
    state = load_state()
    log("request method={} path={} skip_auth={}".format(method, path, skip_auth))

    if method == "GET" and path == "/hello":
        log("hello request from client")
        return 200, hello_payload(ip_address, state)

    if method == "POST" and path == "/pair":
        if payload.get("pairing_code") != secrets.PAIRING_CODE:
            log("pair rejected client_name={} reason=incorrect_code".format(payload.get("client_name", "")))
            return 403, {"error": "Incorrect pairing code."}

        state = {
            "pair_token": make_token(),
            "paired_client": payload.get("client_name", "speech-app"),
            "paired_at": time.time(),
        }
        save_state(state)
        log(
            "pair accepted client_name={} token={}...".format(
                state["paired_client"],
                state["pair_token"][:8],
            )
        )
        return 200, {
            "device_name": secrets.DEVICE_NAME,
            "device_id": device_id(),
            "pair_token": state["pair_token"],
            "paired_client": state["paired_client"],
        }

    if not skip_auth and not require_token(headers, state):
        log("auth rejected path={} reason=invalid_token".format(path))
        return 401, {"error": "Missing or invalid pair token."}

    if method == "GET" and path == "/status":
        last_render = load_json(LAST_RENDER_PATH, {})
        log(
            "status requested paired_client={} last_job={}".format(
                state.get("paired_client"),
                last_render.get("job_id"),
            )
        )
        return 200, {
            "device_name": secrets.DEVICE_NAME,
            "device_id": device_id(),
            "paired_client": state.get("paired_client"),
            "last_render": last_render,
        }

    if method == "POST" and path == "/unpair":
        save_state({})
        log("unpair completed")
        return 200, {"ok": True}

    if method == "POST" and path == "/render":
        job_id = "{}-{}".format(device_id()[:6], int(time.time()))
        mode = payload.get("mode", "write")

        render_job = {
            "job_id": job_id,
            "mode": mode,
            "submitted_at": payload.get("submitted_at"),
            "received_at": time.time(),
        }

        if mode == "braille":
            render_job["cells"] = payload.get("cells", [])
            render_job["language"] = payload.get("language", "en")
            render_job["grade"] = payload.get("grade", 1)
            log(
                "render accepted job_id={} mode=braille cells={} language={} grade={}".format(
                    job_id,
                    len(render_job["cells"]),
                    render_job["language"],
                    render_job["grade"],
                )
            )
        else:
            render_job["text"] = payload.get("text", "")
            render_job["font_family"] = payload.get("font_family", "Noto Sans")
            render_job["script"] = payload.get("script", "latin")
            log(
                "render accepted job_id={} mode=write chars={} font={} script={}".format(
                    job_id,
                    len(render_job["text"]),
                    render_job["font_family"],
                    render_job["script"],
                )
            )

        save_json(LAST_RENDER_PATH, render_job)
        return 200, {"accepted": True, "job_id": job_id}

    log("request not found path={}".format(path))
    return 404, {"error": "Not found."}


def handle_request(client, ip_address):
    try:
        request = parse_request(client)
    except ValueError as exc:
        log("request parse failed error={}".format(exc))
        error_response(client, 400, "Bad request: {}".format(exc))
        return

    method, path, headers, payload = request

    try:
        status_code, response_body = dispatch_request(method, path, headers, payload, ip_address)
    except Exception as exc:
        log("dispatch crashed error={}".format(exc))
        error_response(client, 500, "Robot server error: {}".format(exc))
        return

    json_response(client, status_code, response_body)


def serial_write(cdc, data):
    try:
        cdc.write(data)
    except Exception as exc:
        log("serial write error={}".format(exc))


def handle_serial_command(cdc, line, ip_address):
    try:
        cmd = ujson.loads(line)
    except ValueError:
        serial_write(cdc, ujson.dumps({"status": 400, "body": {"error": "Invalid JSON"}}).encode() + b"\n")
        return

    method = cmd.get("method", "GET").upper()
    path = cmd.get("path", "/")
    headers = cmd.get("headers", {})
    payload = cmd.get("body", {})

    try:
        status_code, response_body = dispatch_request(
            method, path, headers, payload, ip_address, skip_auth=True
        )
    except Exception as exc:
        log("serial dispatch crashed error={}".format(exc))
        status_code = 500
        response_body = {"error": "Robot server error: {}".format(exc)}

    serial_write(cdc, ujson.dumps({"status": status_code, "body": response_body}).encode() + b"\n")


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
    if len(serial_buf) > SERIAL_BUF_MAX:
        log("serial buffer overflow, discarding {} bytes".format(len(serial_buf)))
        serial_buf[:] = b""
        return serial_buf
    while True:
        nl = serial_buf.find(b"\n")
        if nl < 0:
            break
        line = bytes(serial_buf[:nl]).strip()
        serial_buf[:] = serial_buf[nl + 1:]
        if line:
            try:
                handle_serial_command(cdc, line.decode(), ip_address)
            except Exception as exc:
                log("serial command error={}".format(exc))
    return serial_buf


def serve():
    serial_buf = bytearray()
    ip_address = "0.0.0.0"

    # Start WiFi connection (non-blocking kick-off)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)

    # Set up serial immediately so USB responds while WiFi connects
    poller = uselect.poll()

    if cdc_data is not None:
        log("CDC data channel available")

    # Wait for WiFi, but service serial commands while waiting
    log("Waiting for Wi-Fi (serial is active)...")
    for _ in range(60):
        if wlan.isconnected():
            break

        time.sleep(0.5)
        if cdc_data is not None:
            serial_buf = drain_serial(cdc_data, serial_buf, ip_address)

    if wlan.isconnected():
        ip_address = wlan.ifconfig()[0]
        log("Robot Wi-Fi ready at http://{}:{}".format(ip_address, secrets.LISTEN_PORT))
    else:
        log("Wi-Fi connection failed. Continuing with USB serial only.")

    log("Pairing code: {}".format(secrets.PAIRING_CODE))

    # Set up TCP/UDP servers (bind even without WiFi — they'll just get no traffic)
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

    while True:
        for sock, _event in poller.poll(1000):
            if sock is tcp_server:
                client, _addr = tcp_server.accept()
                client.setblocking(True)
                client.settimeout(CLIENT_TIMEOUT_SECONDS)
                try:
                    handle_request(client, ip_address)
                except Exception as exc:
                    log("request crashed error={}".format(exc))
                    json_response(client, 500, {"error": "Robot server error: {}".format(exc)})
                finally:
                    client.close()
            elif sock is udp_server:
                handle_discovery(udp_server, ip_address)
        # Always drain CDC after poll — poll never fires POLLIN for CDCInterface
        if cdc_data is not None:
            serial_buf = drain_serial(cdc_data, serial_buf, ip_address)


serve()
