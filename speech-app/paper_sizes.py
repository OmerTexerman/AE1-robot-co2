PAPER_SIZES = {
    "A4": (210, 297),
    "A5": (148, 210),
    "A3": (297, 420),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}

GANTRY_WIDTH_MM = 300
GANTRY_HEIGHT_MM = 300

PAPER_OFFSET = {"x": 0, "y": 0}

DEFAULT_MARGINS = {"top": 10, "right": 10, "bottom": 10, "left": 10}

DEFAULT_PEN_TIP_MM = 0.7
DEFAULT_FONT_SIZE_MM = 5.0


def get_paper_size(name):
    return PAPER_SIZES.get(name)


def list_paper_sizes():
    return [
        {"name": name, "width": w, "height": h}
        for name, (w, h) in PAPER_SIZES.items()
    ]
