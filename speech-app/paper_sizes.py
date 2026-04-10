PAPER_SIZES = {
    "A4": (210, 297),
    "A5": (148, 210),
    "A3": (297, 420),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}

# Measured work area of the assembled CoreXY gantry, in mm.
# These come from the calibration sweep on 2026-04-09:
#   travel_x = 254.225 mm  -> 247.225 mm reachable from logical origin
#                             after the 5 mm home backoff and 2 mm soft margin
#   travel_y = 212.475 mm  -> 205.475 mm reachable similarly
# Anything outside this rectangle will be rejected by the firmware soft limits,
# so the toolpath generator should not place geometry beyond it.
GANTRY_WIDTH_MM = 247.0
GANTRY_HEIGHT_MM = 205.0

# Default paper offset (top-left of the paper, in machine mm). The user can
# override this in the preview modal to match where their paper actually sits
# on the print bed.
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
