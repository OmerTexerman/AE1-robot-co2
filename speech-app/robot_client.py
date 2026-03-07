from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import ipaddress
import json
import os
import socket
import threading
from urllib.parse import urlparse, urlunparse

import psutil
import requests

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None


DEFAULT_PORT = 8080
REQUEST_TIMEOUT_SECONDS = 4
SERIAL_TIMEOUT_SECONDS = 2
DISCOVERY_PORT = 9090
DISCOVERY_MAGIC = "AE1_DISCOVERY_V1"
UDP_DISCOVERY_TIMEOUT_SECONDS = 0.45
HELLO_PROBE_TIMEOUT_SECONDS = 0.4
MAX_DISCOVERY_WORKERS = 48
MAX_SCAN_NETWORKS = 4
PICO_USB_VID = 0x2E8A
TRANSPORT_HTTP = "http"
TRANSPORT_SERIAL = "serial"
DEFAULT_DEVICE_NAME = "Pico 2 W"
DEFAULT_DEVICE_ID = "unknown"


class RobotClientError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Transport abstraction
# ---------------------------------------------------------------------------

class Transport(ABC):
    @abstractmethod
    def request(self, method: str, path: str, headers: dict | None = None, json_body: dict | None = None) -> dict:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @staticmethod
    def _raise_for_status(status_code: int, body: dict) -> None:
        if status_code >= 400:
            message = body.get("error", f"Robot request failed with status {status_code}.")
            raise RobotClientError(message)


class HttpTransport(Transport):
    def __init__(self, base_url: str):
        self._base_url = base_url

    def request(self, method: str, path: str, headers: dict | None = None, json_body: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        try:
            response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers, json=json_body)
        except requests.RequestException as exc:
            raise RobotClientError(f"Unable to reach robot: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RobotClientError("Robot returned an invalid response.") from exc

        self._raise_for_status(response.status_code, payload)
        return payload

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    def __init__(self, port: str):
        self._port_path = port
        self._lock = threading.Lock()
        self._conn: "serial.Serial | None" = None

    def _open(self) -> "serial.Serial":
        if self._conn is not None and self._conn.is_open:
            return self._conn
        if serial is None:
            raise RobotClientError("pyserial is not installed.")
        try:
            self._conn = serial.Serial(self._port_path, baudrate=115200, timeout=SERIAL_TIMEOUT_SECONDS)
        except serial.SerialException as exc:
            raise RobotClientError(f"Cannot open USB port {self._port_path}: {exc}") from exc
        return self._conn

    def request(self, method: str, path: str, headers: dict | None = None, json_body: dict | None = None) -> dict:
        cmd = {"method": method.upper(), "path": path}
        if json_body:
            cmd["body"] = json_body
        line = json.dumps(cmd, separators=(",", ":")) + "\n"

        with self._lock:
            try:
                conn = self._open()
                conn.write(line.encode())
                conn.flush()
                raw = conn.readline()
            except (serial.SerialException, OSError) as exc:
                self._close_internal()
                raise RobotClientError(f"USB serial communication failed: {exc}") from exc

        if not raw:
            raise RobotClientError("No response from robot over USB serial (timeout).")

        try:
            envelope = json.loads(raw.decode().strip())
        except (ValueError, UnicodeDecodeError) as exc:
            raise RobotClientError(f"Invalid response from robot over USB serial: {exc}") from exc

        status = envelope.get("status", 200)
        body = envelope.get("body", {})

        self._raise_for_status(status, body)
        return body

    def _close_internal(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def close(self) -> None:
        with self._lock:
            self._close_internal()


_serial_transports: dict[str, SerialTransport] = {}
_serial_transports_lock = threading.Lock()


def get_transport(config: dict) -> Transport:
    if config.get("transport") == TRANSPORT_SERIAL:
        port = config["serial_port"]
        with _serial_transports_lock:
            if port not in _serial_transports:
                _serial_transports[port] = SerialTransport(port)
            return _serial_transports[port]
    return HttpTransport(config["base_url"])


def close_transport(config: dict) -> None:
    if config.get("transport") != TRANSPORT_SERIAL:
        return
    port = config.get("serial_port", "")
    with _serial_transports_lock:
        transport = _serial_transports.pop(port, None)
    if transport is not None:
        transport.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _robot_key(robot: dict) -> str:
    return f"{robot['host']}:{robot['port']}"


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


def auth_headers(config: dict) -> dict[str, str] | None:
    token = config.get("pair_token")
    if not token:
        return None
    return {"X-Pair-Token": token}


# ---------------------------------------------------------------------------
# High-level robot operations (transport-aware)
# ---------------------------------------------------------------------------

def pair_robot(host: str, port: int, pairing_code: str, client_name: str) -> dict:
    base_url = build_base_url(host, port)
    config = {"base_url": base_url, "transport": TRANSPORT_HTTP}
    transport = get_transport(config)

    hello = transport.request("GET", "/hello")
    pairing = transport.request("POST", "/pair", json_body={
        "pairing_code": pairing_code,
        "client_name": client_name,
    })

    return {
        "transport": TRANSPORT_HTTP,
        "base_url": base_url,
        "host": host.strip(),
        "port": port,
        "device_name": pairing.get("device_name", hello.get("device_name", DEFAULT_DEVICE_NAME)),
        "device_id": pairing.get("device_id", hello.get("device_id", DEFAULT_DEVICE_ID)),
        "client_name": client_name,
        "pair_token": pairing["pair_token"],
        "paired_at": datetime.now(timezone.utc).isoformat(),
    }


def pair_robot_usb(serial_port: str, client_name: str) -> dict:
    config = {"transport": TRANSPORT_SERIAL, "serial_port": serial_port}
    transport = get_transport(config)

    hello = transport.request("GET", "/hello")

    return {
        "transport": TRANSPORT_SERIAL,
        "serial_port": serial_port,
        "base_url": f"serial://{serial_port}",
        "host": serial_port,
        "port": 0,
        "device_name": hello.get("device_name", DEFAULT_DEVICE_NAME),
        "device_id": hello.get("device_id", DEFAULT_DEVICE_ID),
        "client_name": client_name,
        "pair_token": None,
        "paired_at": datetime.now(timezone.utc).isoformat(),
    }


def _transport_request(config: dict, method: str, path: str, json_body: dict | None = None) -> dict:
    transport = get_transport(config)
    return transport.request(method, path, headers=auth_headers(config), json_body=json_body)


def fetch_status(config: dict) -> dict:
    return _transport_request(config, "GET", "/status")


def unpair_robot(config: dict) -> dict:
    return _transport_request(config, "POST", "/unpair")


def send_render_job(config: dict, text: str, font_family: str, script: str) -> dict:
    return _transport_request(config, "POST", "/render", json_body={
        "mode": "write",
        "text": text,
        "font_family": font_family,
        "script": script,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })


def send_braille_job(
    config: dict,
    cells: list[list[int]],
    language: str,
    grade: int,
) -> dict:
    return _transport_request(config, "POST", "/render", json_body={
        "mode": "braille",
        "cells": cells,
        "language": language,
        "grade": grade,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })


def interface_ipv4_configs() -> list[dict[str, str]]:
    configs: list[dict[str, str]] = []
    interface_addrs = psutil.net_if_addrs()
    interface_stats = psutil.net_if_stats()

    for interface_name, addresses in interface_addrs.items():
        stats = interface_stats.get(interface_name)
        if stats is None or not stats.isup:
            continue
        if interface_name == "lo":
            continue

        for address_info in addresses:
            if address_info.family != socket.AF_INET:
                continue

            address = address_info.address
            netmask = address_info.netmask
            if not address or not netmask:
                continue
            if address.startswith("127.") or address.startswith("169.254."):
                continue

            iface = ipaddress.IPv4Interface(f"{address}/{netmask}")
            configs.append(
                {
                    "interface": interface_name,
                    "address": address,
                    "netmask": netmask,
                    "broadcast": address_info.broadcast or str(iface.network.broadcast_address),
                    "network": iface.network,
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
    if not isinstance(payload, dict):
        return None

    host = payload.get("ip_address") or fallback_host
    if not host:
        return None

    try:
        port = int(payload.get("listen_port", DEFAULT_PORT))
    except (TypeError, ValueError):
        return None

    return {
        "host": host,
        "port": port,
        "device_name": payload.get("device_name", DEFAULT_DEVICE_NAME),
        "device_id": payload.get("device_id", DEFAULT_DEVICE_ID),
        "paired": bool(payload.get("paired")),
    }


def normalize_candidate_ports(candidate_ports: list[int] | None) -> list[int]:
    if not candidate_ports:
        return [DEFAULT_PORT]

    normalized_ports: list[int] = []
    seen: set[int] = set()

    for port in candidate_ports:
        try:
            normalized_port = int(port)
        except (TypeError, ValueError):
            continue

        if not 1 <= normalized_port <= 65535 or normalized_port in seen:
            continue

        normalized_ports.append(normalized_port)
        seen.add(normalized_port)

    return normalized_ports or [DEFAULT_PORT]


def udp_discovery(discovery_port: int) -> list[dict]:
    message = DISCOVERY_MAGIC.encode("utf-8")
    discovered: dict[str, dict] = {}

    for bind_address, broadcast_address in discovery_broadcast_targets():
        try:
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
                    discovered[_robot_key(robot)] = robot
        except OSError:
            continue

    return list(discovered.values())


def probe_networks() -> list[ipaddress.IPv4Network]:
    networks: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()

    for config in interface_ipv4_configs():
        network = config["network"]

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
            f"{build_base_url(host, port)}/hello",
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

    try:
        return normalize_discovered_robot(payload, host)
    except (TypeError, ValueError):
        return None


def active_hello_probe(candidate_ports: list[int] | None = None) -> list[dict]:
    discovered: dict[str, dict] = {}
    candidate_hosts: list[str] = []
    ports = normalize_candidate_ports(candidate_ports)

    for network in probe_networks():
        for host in network.hosts():
            candidate_hosts.append(str(host))

    with ThreadPoolExecutor(max_workers=MAX_DISCOVERY_WORKERS) as executor:
        futures = {
            executor.submit(hello_probe, host, port): (host, port)
            for host in candidate_hosts
            for port in ports
        }

        for future in as_completed(futures):
            try:
                robot = future.result()
            except Exception:
                continue
            if robot is None:
                continue
            discovered[_robot_key(robot)] = robot
            # One robot found is enough — cancel remaining probes
            for pending in futures:
                pending.cancel()
            break

    return list(discovered.values())


def _list_pico_ports() -> list:
    if serial is None:
        return []
    return [p for p in serial.tools.list_ports.comports() if p.vid == PICO_USB_VID]


def _pick_data_port(pico_ports: list) -> str | None:
    if not pico_ports:
        return None

    # Group by serial number (one physical Pico = one serial number)
    by_serial: dict[str, list] = {}
    for p in pico_ports:
        key = p.serial_number or p.device
        by_serial.setdefault(key, []).append(p)

    # For each Pico, pick the data port:
    # - The REPL port is labeled interface="Board CDC" by MicroPython
    # - The data CDC port has interface=None
    # - If there's only one port (no dual CDC), skip it — that's just the REPL
    for ports in by_serial.values():
        if len(ports) < 2:
            continue

        for p in ports:
            if getattr(p, "interface", None) != "Board CDC":
                return p.device

    return None


def discover_usb_robots() -> list[dict]:
    pico_ports = _list_pico_ports()
    data_port = _pick_data_port(pico_ports)
    if data_port is None:
        return []

    config = {"transport": TRANSPORT_SERIAL, "serial_port": data_port}
    try:
        transport = get_transport(config)
        hello = transport.request("GET", "/hello")
    except RobotClientError:
        return []
    finally:
        close_transport(config)

    return [{
        "host": data_port,
        "port": 0,
        "device_name": hello.get("device_name", DEFAULT_DEVICE_NAME),
        "device_id": hello.get("device_id", DEFAULT_DEVICE_ID),
        "paired": bool(hello.get("paired")),
        "usb": True,
        "serial_port": data_port,
    }]


def serial_port_exists(port: str) -> bool:
    return os.path.exists(port)


def discover_robots(
    discovery_port: int = DISCOVERY_PORT,
    candidate_ports: list[int] | None = None,
) -> list[dict]:
    discovered: dict[str, dict] = {}

    for robot in discover_usb_robots():
        key = f"usb:{robot['serial_port']}"
        discovered[key] = robot

    for robot in udp_discovery(discovery_port):
        discovered[_robot_key(robot)] = robot

    if not any(not r.get("usb") for r in discovered.values()):
        for robot in active_hello_probe(candidate_ports):
            discovered[_robot_key(robot)] = robot

    usb_robots = sorted(
        (r for r in discovered.values() if r.get("usb")),
        key=lambda item: item["host"],
    )
    network_robots = sorted(
        (r for r in discovered.values() if not r.get("usb")),
        key=lambda item: (item["host"], item["port"]),
    )

    return usb_robots + network_robots
