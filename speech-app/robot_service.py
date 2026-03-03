from flask import Flask

from robot_client import (
    RobotClientError,
    discover_robots,
    fetch_status,
    pair_robot,
    unpair_robot,
)


def init_robot_session(app: Flask) -> None:
    app.config["CURRENT_ROBOT_CONFIG"] = None


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


def unpair_current_robot(config: dict) -> str | None:
    try:
        unpair_robot(config)
        return None
    except RobotClientError as exc:
        return str(exc)
