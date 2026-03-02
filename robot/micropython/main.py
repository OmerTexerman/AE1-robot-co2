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


STATE_PATH = "pairing_state.json"
LAST_RENDER_PATH = "last_render.json"
BUFFER_SIZE = 4096
DISCOVERY_MAGIC = b"AE1_DISCOVERY_V1"
CLIENT_TIMEOUT_SECONDS = 3


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


def device_id():
    return ubinascii.hexlify(unique_id()).decode()


def make_token():
    return "{:08x}{:08x}".format(urandom.getrandbits(32), urandom.getrandbits(32))


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan.ifconfig()[0]

    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
    for _ in range(30):
        if wlan.isconnected():
            return wlan.ifconfig()[0]
        time.sleep(1)

    raise RuntimeError("Wi-Fi connection failed.")


def json_response(client, status_code, payload):
    body = ujson.dumps(payload)
    reason = "OK" if status_code < 400 else "ERROR"
    headers = [
        "HTTP/1.1 {} {}".format(status_code, reason),
        "Content-Type: application/json",
        "Content-Length: {}".format(len(body)),
        "Connection: close",
        "",
        body,
    ]
    client.send("\r\n".join(headers).encode())


def error_response(client, status_code, message):
    json_response(client, status_code, {"error": message})


def parse_request(client):
    data = b""
    while b"\r\n\r\n" not in data and len(data) < BUFFER_SIZE:
        try:
            chunk = client.recv(512)
        except OSError as exc:
            raise ValueError("socket read failed: {}".format(exc))
        if not chunk:
            raise ValueError("client disconnected before request headers completed")
        data += chunk

    if b"\r\n\r\n" not in data:
        raise ValueError("request headers too large or incomplete")

    header_blob, _, body = data.partition(b"\r\n\r\n")
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
    while len(body) < content_length:
        try:
            chunk = client.recv(min(512, content_length - len(body)))
        except OSError as exc:
            raise ValueError("socket body read failed: {}".format(exc))
        if not chunk:
            raise ValueError("client disconnected before request body completed")
        body += chunk

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


def handle_request(client, ip_address):
    try:
        request = parse_request(client)
    except ValueError as exc:
        log("request parse failed error={}".format(exc))
        error_response(client, 400, "Bad request: {}".format(exc))
        return

    method, path, headers, payload = request
    state = load_json(STATE_PATH, {})
    log("request method={} path={}".format(method, path))

    if method == "GET" and path == "/hello":
        log("hello request from client")
        json_response(client, 200, hello_payload(ip_address, state))
        return

    if method == "POST" and path == "/pair":
        if payload.get("pairing_code") != secrets.PAIRING_CODE:
            log("pair rejected client_name={} reason=incorrect_code".format(payload.get("client_name", "")))
            json_response(client, 403, {"error": "Incorrect pairing code."})
            return

        state = {
            "pair_token": make_token(),
            "paired_client": payload.get("client_name", "speech-app"),
            "paired_at": time.time(),
        }
        save_json(STATE_PATH, state)
        log(
            "pair accepted client_name={} token={}...".format(
                state["paired_client"],
                state["pair_token"][:8],
            )
        )
        json_response(
            client,
            200,
            {
                "device_name": secrets.DEVICE_NAME,
                "device_id": device_id(),
                "pair_token": state["pair_token"],
                "paired_client": state["paired_client"],
            },
        )
        return

    if not require_token(headers, state):
        log("auth rejected path={} reason=invalid_token".format(path))
        json_response(client, 401, {"error": "Missing or invalid pair token."})
        return

    if method == "GET" and path == "/status":
        last_render = load_json(LAST_RENDER_PATH, {})
        log(
            "status requested paired_client={} last_job={}".format(
                state.get("paired_client"),
                last_render.get("job_id"),
            )
        )
        json_response(
            client,
            200,
            {
                "device_name": secrets.DEVICE_NAME,
                "device_id": device_id(),
                "paired_client": state.get("paired_client"),
                "last_render": last_render,
            },
        )
        return

    if method == "POST" and path == "/unpair":
        save_json(STATE_PATH, {})
        log("unpair completed")
        json_response(client, 200, {"ok": True})
        return

    if method == "POST" and path == "/render":
        job_id = "{}-{}".format(device_id()[:6], int(time.time()))
        render_job = {
            "job_id": job_id,
            "text": payload.get("text", ""),
            "font_family": payload.get("font_family", "Noto Sans"),
            "script": payload.get("script", "latin"),
            "submitted_at": payload.get("submitted_at"),
            "received_at": time.time(),
        }
        save_json(LAST_RENDER_PATH, render_job)
        log(
            "render accepted job_id={} chars={} font={} script={}".format(
                job_id,
                len(render_job["text"]),
                render_job["font_family"],
                render_job["script"],
            )
        )
        json_response(client, 200, {"accepted": True, "job_id": job_id})
        return

    log("request not found path={}".format(path))
    json_response(client, 404, {"error": "Not found."})


def handle_discovery(discovery_socket, ip_address):
    try:
        payload, address = discovery_socket.recvfrom(256)
    except OSError:
        return

    if payload != DISCOVERY_MAGIC:
        return

    log("discovery reply sent to {}:{}".format(address[0], address[1]))
    response = ujson.dumps(hello_payload(ip_address, load_json(STATE_PATH, {})))
    discovery_socket.sendto(response.encode(), address)


def serve():
    ip_address = connect_wifi()
    log("Robot Wi-Fi ready at http://{}:{}".format(ip_address, secrets.LISTEN_PORT))
    log("Pairing code: {}".format(secrets.PAIRING_CODE))

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

    poller = uselect.poll()
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


serve()
