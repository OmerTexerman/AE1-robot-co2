import json
from pathlib import Path


STORE_PATH = Path(__file__).resolve().parent / "data" / "paired_robot.json"


def load_robot() -> dict | None:
    if not STORE_PATH.exists():
        return None

    return json.loads(STORE_PATH.read_text(encoding="utf-8"))


def save_robot(config: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def clear_robot() -> None:
    STORE_PATH.unlink(missing_ok=True)
