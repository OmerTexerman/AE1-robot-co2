from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import socket
import struct
from urllib.parse import urlparse, urlunparse

import requests


DEFAULT_PORT = 8080
REQUEST_TIMEOUT_SECONDS = 4
DISCOVERY_PORT = 9090
DISCOVERY_MAGIC = "AE1_DISCOVERY_V1"
UDP_DISCOVERY_TIMEOUT_SECONDS = 0.45
HELLO_PROBE_TIMEOUT_SECONDS = 0.4
MAX_DISCOVERY_WORKERS = 48
MAX_SCAN_NETWORKS = 4

SIOCGIFFLAGS = 0x8913
SIOCGIFADDR = 0x8915
SIOCGIFBRDADDR = 0x8919
SIOCGIFNETMASK = 0x891B
IFF_UP = 0x1
IFF_LOOPBACK = 0x8


class RobotClientError(RuntimeError):
    pass


def build_base_url(host: str, port: int) -> str:
    host = host.strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        parsed = urlparse(host)
        if not parsed.hostname:
            return host

        netloc = parsed.hostname
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        elif port:
            netloc = f"{netloc}:{port}"

        return urlunparse((parsed.scheme, netloc, "", "", "", ""))
    return f"http://{host}:{port}"


def auth_headers(config: dict) -> dict[str, str]:
    return {"X-Pair-Token": config["pair_token"]}


def request_json(method: str, url: str, **kwargs) -> dict:
    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as exc:
        raise RobotClientError(f"Unable to reach robot: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise RobotClientError("Robot returned an invalid response.") from exc

    if not response.ok:
        message = payload.get("error", f"Robot request failed with status {response.status_code}.")
        raise RobotClientError(message)

    return payload


def pair_robot(host: str, port: int, pairing_code: str, client_name: str) -> dict:
    base_url = build_base_url(host, port)
    hello = request_json("get", f"{base_url}/hello")
    pairing = request_json(
        "post",
        f"{base_url}/pair",
        json={
            "pairing_code": pairing_code,
            "client_name": client_name,
        },
    )

    return {
        "base_url": base_url,
        "host": host.strip(),
        "port": port,
        "device_name": pairing.get("device_name", hello.get("device_name", "Pico 2 W")),
        "device_id": pairing.get("device_id", hello.get("device_id", "unknown")),
        "client_name": client_name,
        "pair_token": pairing["pair_token"],
        "paired_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_status(config: dict) -> dict:
    return request_json("get", f"{config['base_url']}/status", headers=auth_headers(config))


def unpair_robot(config: dict) -> dict:
    return request_json("post", f"{config['base_url']}/unpair", headers=auth_headers(config))


def send_render_job(config: dict, text: str, font_family: str, script: str) -> dict:
    return request_json(
        "post",
        f"{config['base_url']}/render",
        headers=auth_headers(config),
        json={
            "text": text,
            "font_family": font_family,
            "script": script,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def ifreq_bytes(interface_name: str) -> bytes:
    return struct.pack("256s", interface_name[:15].encode("utf-8"))


def ioctl_ipv4(control_socket: socket.socket, request: int, interface_name: str) -> str | None:
    try:
        response = fcntl.ioctl(control_socket.fileno(), request, ifreq_bytes(interface_name))
    except OSError:
        return None
    return socket.inet_ntoa(response[20:24])


def ioctl_flags(control_socket: socket.socket, interface_name: str) -> int | None:
    try:
        response = fcntl.ioctl(control_socket.fileno(), SIOCGIFFLAGS, ifreq_bytes(interface_name))
    except OSError:
        return None
    return struct.unpack("H", response[16:18])[0]


def interface_ipv4_configs() -> list[dict[str, str]]:
    configs: list[dict[str, str]] = []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control_socket:
        for _index, interface_name in socket.if_nameindex():
            flags = ioctl_flags(control_socket, interface_name)
            if flags is None or not (flags & IFF_UP) or (flags & IFF_LOOPBACK):
                continue

            address = ioctl_ipv4(control_socket, SIOCGIFADDR, interface_name)
            netmask = ioctl_ipv4(control_socket, SIOCGIFNETMASK, interface_name)
            if not address or not netmask:
                continue

            if address.startswith("127.") or address.startswith("169.254."):
                continue

            broadcast = ioctl_ipv4(control_socket, SIOCGIFBRDADDR, interface_name)
            network = ipaddress.IPv4Interface(f"{address}/{netmask}").network
            configs.append(
                {
                    "interface": interface_name,
                    "address": address,
                    "netmask": netmask,
                    "broadcast": broadcast or str(network.broadcast_address),
                }
            )

    return configs


def discovery_broadcast_targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = [("", "255.255.255.255")]
    seen = {"255.255.255.255"}

    for config in interface_ipv4_configs():
        broadcast = config["broadcast"]
        if broadcast not in seen:
            targets.append((config["address"], broadcast))
            seen.add(broadcast)

    return targets


def normalize_discovered_robot(payload: dict, fallback_host: str) -> dict | None:
    host = payload.get("ip_address") or fallback_host
    if not host:
        return None

    return {
        "host": host,
        "port": int(payload.get("listen_port", DEFAULT_PORT)),
        "device_name": payload.get("device_name", "Pico 2 W"),
        "device_id": payload.get("device_id", "unknown"),
        "paired": bool(payload.get("paired")),
    }


def udp_discovery(discovery_port: int) -> list[dict]:
    message = DISCOVERY_MAGIC.encode("utf-8")
    discovered: dict[str, dict] = {}

    for bind_address, broadcast_address in discovery_broadcast_targets():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(UDP_DISCOVERY_TIMEOUT_SECONDS)
            sock.bind((bind_address, 0))
            sock.sendto(message, (broadcast_address, discovery_port))

            while True:
                try:
                    packet, address = sock.recvfrom(2048)
                except socket.timeout:
                    break

                try:
                    payload = json.loads(packet.decode("utf-8"))
                except ValueError:
                    continue

                robot = normalize_discovered_robot(payload, address[0])
                if robot is None:
                    continue
                discovered[f"{robot['host']}:{robot['port']}"] = robot

    return list(discovered.values())


def probe_networks() -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()

    for config in interface_ipv4_configs():
        interface = ipaddress.IPv4Interface(f"{config['address']}/{config['netmask']}")
        network = interface.network

        # Avoid unbounded scans on large networks. Reduce to the interface's /24.
        if network.prefixlen < 24:
            network = ipaddress.IPv4Interface(f"{config['address']}/24").network

        key = str(network)
        if key not in seen:
            networks.append(network)
            seen.add(key)

        if len(networks) >= MAX_SCAN_NETWORKS:
            break

    return networks


def hello_probe(host: str, port: int = DEFAULT_PORT) -> dict | None:
    try:
        response = requests.get(
            f"http://{host}:{port}/hello",
            timeout=HELLO_PROBE_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None

    if not response.ok:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    return normalize_discovered_robot(payload, host)


def active_hello_probe() -> list[dict]:
    discovered: dict[str, dict] = {}
    candidate_hosts: list[str] = []

    for network in probe_networks():
        for host in network.hosts():
            candidate_hosts.append(str(host))

    with ThreadPoolExecutor(max_workers=MAX_DISCOVERY_WORKERS) as executor:
        futures = {
            executor.submit(hello_probe, host): host
            for host in candidate_hosts
        }

        for future in as_completed(futures):
            robot = future.result()
            if robot is None:
                continue
            discovered[f"{robot['host']}:{robot['port']}"] = robot

    return list(discovered.values())


def discover_robots(discovery_port: int = DISCOVERY_PORT) -> list[dict]:
    discovered: dict[str, dict] = {}

    for robot in udp_discovery(discovery_port):
        discovered[f"{robot['host']}:{robot['port']}"] = robot

    if not discovered:
        for robot in active_hello_probe():
            discovered[f"{robot['host']}:{robot['port']}"] = robot

    return sorted(discovered.values(), key=lambda item: (item["host"], item["port"]))
