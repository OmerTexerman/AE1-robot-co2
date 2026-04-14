from collections.abc import Mapping, Sequence

from google_fonts import DEFAULT_FONT_FAMILY
from paper_sizes import DEFAULT_FONT_SIZE_MM, DEFAULT_MARGINS, DEFAULT_PEN_TIP_MM, PAPER_OFFSET, get_paper_size

DEFAULT_PORT = 8080
DEFAULT_CLIENT_NAME = "speech-app"
DEFAULT_PAPER_SIZE_NAME = "A4"
VALID_TOOLPATH_MODES = {"write", "braille"}
VALID_RENDER_MODES = {"outline", "filled", "centerline"}
VALID_OPERATION_TYPES = {"draw", "travel", "punch"}
_MISSING = object()


def parse_string(
    value: object,
    field_name: str,
    *,
    default: str | None = None,
    required: bool = False,
) -> str:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value.strip()
    else:
        raise ValueError(f"{field_name} must be a string.")

    if text:
        return text
    if required:
        raise ValueError(f"{field_name} is required.")
    return default or ""


def parse_port(value: object, error_message: str, default: int = DEFAULT_PORT) -> int:
    if value in (None, ""):
        return default

    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc

    if not 1 <= port <= 65535:
        raise ValueError(error_message)

    return port


def parse_pairing_request(payload: Mapping[str, object]) -> tuple[str, int, str, str]:
    host = parse_string(payload.get("host"), "Robot host or IP", required=True)
    pairing_code = parse_string(payload.get("pairing_code"), "Pairing code", required=True)
    client_name = parse_string(payload.get("client_name"), "Client name", default=DEFAULT_CLIENT_NAME)
    port = parse_port(payload.get("port"), "Robot port must be a number.")
    return host, port, pairing_code, client_name


def parse_float(value: object, error_message: str, *, default: float | object = _MISSING) -> float:
    if value in (None, ""):
        if default is _MISSING:
            raise ValueError(error_message)
        return float(default)

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc


def parse_optional_int(value: object, error_message: str) -> int | None:
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc


def parse_int(value: object, error_message: str, *, default: int | object = _MISSING) -> int:
    if value in (None, ""):
        if default is _MISSING:
            raise ValueError(error_message)
        return int(default)

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error_message) from exc


def parse_toolpath_mode(value: object) -> str:
    mode = parse_string(value, "Mode", default="write").lower()
    if mode not in VALID_TOOLPATH_MODES:
        raise ValueError("Mode must be 'write' or 'braille'.")
    return mode


def parse_render_mode(value: object) -> str:
    render_mode = parse_string(value, "Render mode", default="outline").lower()
    if render_mode not in VALID_RENDER_MODES:
        raise ValueError("Render mode must be 'outline', 'filled', or 'centerline'.")
    return render_mode


def parse_numeric_mapping(
    value: object,
    defaults: Mapping[str, float | int],
    label: str,
) -> dict[str, float]:
    if value is None:
        return {key: float(default) for key, default in defaults.items()}
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")

    parsed: dict[str, float] = {}
    for key, default in defaults.items():
        parsed[key] = parse_float(value.get(key, default), f"{label} values must be numbers.")
    return parsed


def resolve_paper_size(payload: Mapping[str, object]) -> tuple[float, float]:
    paper_name = parse_string(payload.get("paper_size"), "Paper size", default=DEFAULT_PAPER_SIZE_NAME)
    paper = get_paper_size(paper_name)
    if paper:
        return paper

    width = payload.get("paper_width")
    height = payload.get("paper_height")
    if width in (None, "") and height in (None, ""):
        return get_paper_size(DEFAULT_PAPER_SIZE_NAME)
    if width in (None, "") or height in (None, ""):
        raise ValueError("Both custom paper dimensions are required.")

    paper_width = parse_float(width, "Invalid custom paper dimensions.")
    paper_height = parse_float(height, "Invalid custom paper dimensions.")
    if paper_width <= 0 or paper_height <= 0:
        raise ValueError("Custom paper dimensions must be greater than zero.")
    return paper_width, paper_height


def parse_toolpath_request(payload: Mapping[str, object]) -> dict[str, object]:
    request_data: dict[str, object] = {
        "text": parse_string(payload.get("text"), "Text", required=True),
        "mode": parse_toolpath_mode(payload.get("mode")),
        "paper_size": resolve_paper_size(payload),
        "margins": parse_numeric_mapping(payload.get("margins"), DEFAULT_MARGINS, "Margins"),
        "paper_offset": parse_numeric_mapping(payload.get("paper_offset"), PAPER_OFFSET, "Paper offset"),
    }

    if request_data["mode"] == "braille":
        from braille_translator import normalize_grade

        request_data["language"] = parse_string(payload.get("language"), "Language", default="en")
        request_data["grade"] = normalize_grade(payload.get("grade"))
        return request_data

    request_data["font_family"] = parse_string(
        payload.get("font_family"),
        "Font family",
        default=DEFAULT_FONT_FAMILY,
    )
    request_data["font_size_mm"] = parse_float(
        payload.get("font_size_mm"),
        "Font size must be a number.",
        default=DEFAULT_FONT_SIZE_MM,
    )
    request_data["pen_tip_mm"] = parse_float(
        payload.get("pen_tip_mm"),
        "Pen tip must be a number.",
        default=DEFAULT_PEN_TIP_MM,
    )
    request_data["render_mode"] = parse_render_mode(payload.get("render_mode"))
    return request_data


def validate_operations(operations: object) -> None:
    if not isinstance(operations, list) or not operations:
        raise ValueError("No operations to send.")

    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, Mapping):
            raise ValueError(f"Operation {index} must be an object.")

        op_type = operation.get("type")
        if op_type not in VALID_OPERATION_TYPES:
            raise ValueError(f"Operation {index} has an invalid type.")

        if op_type == "punch":
            _validate_point(operation.get("point"), f"Operation {index} point")
            continue

        points = operation.get("points")
        if not isinstance(points, list):
            raise ValueError(f"Operation {index} points must be a list.")
        if op_type == "draw" and len(points) < 2:
            raise ValueError(f"Operation {index} draw path must contain at least two points.")
        if op_type == "travel" and not points:
            raise ValueError(f"Operation {index} travel path must contain at least one point.")

        for point_index, point in enumerate(points, start=1):
            _validate_point(point, f"Operation {index} point {point_index}")


def _validate_point(value: object, label: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise ValueError(f"{label} must contain exactly two coordinates.")
    parse_float(value[0], f"{label} coordinates must be numbers.")
    parse_float(value[1], f"{label} coordinates must be numbers.")
