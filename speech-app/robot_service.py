from flask import Flask

from robot_client import (
    RobotClientError,
    TRANSPORT_SERIAL,
    close_transport,
    discover_robots,
    fetch_status,
    pair_robot,
    pair_robot_usb,
    serial_port_exists,
    unpair_robot,
)


def init_robot_session(app: Flask) -> None:
    app.config["CURRENT_ROBOT_CONFIG"] = None


def serialize_robot_config(config: dict | None) -> dict | None:
    if not config:
        return None

    result = {
        "base_url": config["base_url"],
        "host": config["host"],
        "port": config["port"],
        "device_name": config["device_name"],
        "device_id": config["device_id"],
        "client_name": config["client_name"],
        "paired_at": config["paired_at"],
        "transport": config.get("transport", "http"),
    }
    if config.get("transport") == TRANSPORT_SERIAL:
        result["serial_port"] = config.get("serial_port", "")
    return result


def unpaired_robot_payload(warning: str | None = None) -> dict:
    payload = {"paired": False, "robot": None}
    if warning:
        payload["warning"] = warning
    return payload


def paired_robot_payload(
    config: dict,
    *,
    connected: bool,
    status: dict | None,
    error: str | None = None,
) -> dict:
    payload = {
        "paired": True,
        "robot": serialize_robot_config(config),
        "connected": connected,
        "status": status,
    }
    if error is not None:
        payload["error"] = error
    return payload


def get_current_robot(app: Flask) -> dict | None:
    return app.config["CURRENT_ROBOT_CONFIG"]


def set_current_robot(app: Flask, config: dict | None) -> None:
    app.config["CURRENT_ROBOT_CONFIG"] = config


def get_robot_connection_state(logger, config: dict) -> dict:
    if config.get("transport") == TRANSPORT_SERIAL:
        port = config.get("serial_port", "")
        if not serial_port_exists(port):
            logger.warning(
                "robot_state usb_disconnected device=%s serial_port=%s",
                config.get("device_name"),
                port,
            )
            return {"connected": False, "status": None, "error": None, "disconnected": True}

    try:
        status = fetch_status(config)
        logger.info(
            "robot_state ok device=%s host=%s port=%s",
            config["device_name"],
            config["host"],
            config["port"],
        )
        return {"connected": True, "status": status, "error": None}
    except RobotClientError as exc:
        logger.warning(
            "robot_state failed device=%s host=%s port=%s error=%s",
            config["device_name"],
            config["host"],
            config["port"],
            exc,
        )
        return {"connected": False, "status": None, "error": str(exc)}


def discover_available_robots(port: int, current_robot: dict | None = None) -> list[dict]:
    candidate_ports = [port]
    if current_robot and current_robot["port"] not in candidate_ports:
        candidate_ports.append(int(current_robot["port"]))
    return discover_robots(candidate_ports=candidate_ports)


def pair_with_robot(logger, host: str, port: int, pairing_code: str, client_name: str) -> tuple[dict, dict]:
    config = pair_robot(host=host, port=port, pairing_code=pairing_code, client_name=client_name)
    return config, get_robot_connection_state(logger, config)


def pair_with_robot_usb(logger, serial_port: str, client_name: str) -> tuple[dict, dict]:
    config = pair_robot_usb(serial_port=serial_port, client_name=client_name)
    logger.info(
        "robot_pair_usb device=%s device_id=%s serial_port=%s",
        config["device_name"],
        config["device_id"],
        serial_port,
    )
    return config, get_robot_connection_state(logger, config)


def unpair_current_robot(config: dict) -> str | None:
    if config.get("transport") == TRANSPORT_SERIAL:
        close_transport(config)
        return None
    try:
        unpair_robot(config)
        return None
    except RobotClientError as exc:
        return str(exc)
