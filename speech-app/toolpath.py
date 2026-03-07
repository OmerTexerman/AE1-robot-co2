import logging
import math

from braille_translator import translate_to_braille
from font_renderer import (
    get_font_metrics,
    get_glyph_centerlines,
    get_glyph_outlines,
    get_hershey_glyphs,
    get_hershey_metrics,
    get_ttf_path,
    hatch_fill,
    is_hershey_font,
)
from paper_sizes import DEFAULT_FONT_SIZE_MM, DEFAULT_MARGINS, DEFAULT_PEN_TIP_MM, PAPER_OFFSET

logger = logging.getLogger(__name__)

# Braille cell dimensions (mm)
BRAILLE_DOT_SPACING = 2.5
BRAILLE_CELL_WIDTH = 6.0
BRAILLE_CELL_HEIGHT = 10.0
BRAILLE_WORD_GAP = 12.0


def _distance(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _path_length(points):
    total = 0
    for i in range(1, len(points)):
        total += _distance(points[i - 1], points[i])
    return total


def _reorder_paths_nearest_neighbor(paths, start=(0, 0)):
    """Reorder paths using greedy nearest-neighbor on start/end points.
    Reverses a path if entering from the end is shorter."""
    if not paths:
        return []
    remaining = list(range(len(paths)))
    result = []
    pos = start
    while remaining:
        best_idx = None
        best_dist = float("inf")
        best_reverse = False
        for i in remaining:
            d_start = _distance(pos, paths[i][0])
            d_end = _distance(pos, paths[i][-1])
            if d_start < best_dist:
                best_dist = d_start
                best_idx = i
                best_reverse = False
            if d_end < best_dist:
                best_dist = d_end
                best_idx = i
                best_reverse = True
        remaining.remove(best_idx)
        p = list(reversed(paths[best_idx])) if best_reverse else paths[best_idx]
        result.append(p)
        pos = p[-1]
    return result


def _merge_nearby_endpoints(paths, tolerance):
    """Merge consecutive paths whose endpoints are within tolerance."""
    if not paths:
        return []
    merged = [list(paths[0])]
    for i in range(1, len(paths)):
        if _distance(merged[-1][-1], paths[i][0]) <= tolerance:
            merged[-1].extend(paths[i][1:])
        else:
            merged.append(list(paths[i]))
    return merged


def _reorder_points_nearest_neighbor(points, start=(0, 0)):
    """Reorder discrete points using greedy nearest-neighbor."""
    if not points:
        return []
    remaining = list(range(len(points)))
    result = []
    pos = start
    while remaining:
        best_idx = None
        best_dist = float("inf")
        for i in remaining:
            d = _distance(pos, points[i])
            if d < best_dist:
                best_dist = d
                best_idx = i
        remaining.remove(best_idx)
        result.append(points[best_idx])
        pos = points[best_idx]
    return result


def _word_wrap_glyphs(words_glyphs, max_width):
    """Word wrap using pre-shaped glyph data. Returns list of lines, each line
    is a list of (word_glyphs, word_width) tuples.

    If a single word is wider than max_width, it is broken into chunks that fit.
    """
    lines = []
    current_line = []
    current_width = 0
    space_width = 0

    def _break_word(glyphs, max_w):
        """Break a word's glyphs into chunks that each fit within max_w."""
        chunks = []
        chunk_glyphs = []
        chunk_width = 0
        for g in glyphs:
            if chunk_glyphs and chunk_width + g.advance > max_w:
                chunks.append((chunk_glyphs, chunk_width))
                chunk_glyphs = [g]
                chunk_width = g.advance
            else:
                chunk_glyphs.append(g)
                chunk_width += g.advance
        if chunk_glyphs:
            chunks.append((chunk_glyphs, chunk_width))
        return chunks

    for word_glyphs, word_width, word_space_width in words_glyphs:
        # If the word itself is wider than the available width, break it
        if word_width > max_width:
            if current_line:
                lines.append(current_line)
                current_line = []
                current_width = 0
            for chunk_glyphs, chunk_width in _break_word(word_glyphs, max_width):
                lines.append([(chunk_glyphs, chunk_width)])
            continue

        if not current_line:
            current_line.append((word_glyphs, word_width))
            current_width = word_width
            space_width = word_space_width
        elif current_width + space_width + word_width <= max_width:
            current_line.append((word_glyphs, word_width))
            current_width += space_width + word_width
        else:
            lines.append(current_line)
            current_line = [(word_glyphs, word_width)]
            current_width = word_width

    if current_line:
        lines.append(current_line)

    return lines


def generate_write_toolpath(
    text,
    font_family,
    font_size_mm=DEFAULT_FONT_SIZE_MM,
    paper_size=(210, 297),
    margins=None,
    pen_tip_mm=DEFAULT_PEN_TIP_MM,
    render_mode="outline",
    paper_offset=None,
    optimize=True,
):
    if margins is None:
        margins = dict(DEFAULT_MARGINS)
    if paper_offset is None:
        paper_offset = dict(PAPER_OFFSET)

    paper_w, paper_h = paper_size
    left = margins.get("left", 10)
    right = margins.get("right", 10)
    top = margins.get("top", 10)
    bottom = margins.get("bottom", 10)
    offset_x = paper_offset.get("x", 0)
    offset_y = paper_offset.get("y", 0)

    usable_width = paper_w - left - right
    usable_height = paper_h - top - bottom

    use_hershey = is_hershey_font(font_family)

    if use_hershey:
        metrics = get_hershey_metrics(font_family, font_size_mm)
        # Hershey fonts are already single-stroke, force render_mode
        render_mode = "outline"
    else:
        ttf_path = get_ttf_path(font_family)
        metrics = get_font_metrics(ttf_path, font_size_mm)

    line_height = metrics["line_height"]
    ascender = metrics["ascender"]

    # Split text into paragraphs then words
    paragraphs = text.split("\n")

    # Select glyph extraction function based on render mode and font type
    def extract_glyphs(text_str):
        if use_hershey:
            return get_hershey_glyphs(font_family, text_str, font_size_mm)
        elif render_mode == "centerline":
            return get_glyph_centerlines(ttf_path, text_str, font_size_mm)
        else:
            return get_glyph_outlines(ttf_path, text_str, font_size_mm)

    # Shape each word and measure advance widths
    all_paragraph_words = []
    for para in paragraphs:
        words = para.split()
        if not words:
            all_paragraph_words.append([])
            continue

        # Space width
        space_glyphs = extract_glyphs(" ")
        space_width = space_glyphs[0].advance if space_glyphs else font_size_mm * 0.3

        word_data = []
        for word in words:
            glyphs = extract_glyphs(word)
            word_width = sum(g.advance for g in glyphs)
            word_data.append((glyphs, word_width, space_width))

        all_paragraph_words.append(word_data)

    # Phase 1: Collect all paths
    all_paths = []
    cursor_y = top + offset_y + ascender

    for para_words in all_paragraph_words:
        if not para_words:
            cursor_y += line_height
            continue

        wrapped_lines = _word_wrap_glyphs(para_words, usable_width)

        for line_words in wrapped_lines:
            if cursor_y + metrics["descender"] > paper_h - bottom + offset_y:
                break  # Out of paper

            cursor_x = left + offset_x
            for word_glyphs, word_width in line_words:
                for glyph in word_glyphs:
                    gx = cursor_x + glyph.x_offset
                    gy = cursor_y + glyph.y_offset

                    for path in glyph.paths:
                        translated = [(gx + px, gy + py) for px, py in path]
                        if len(translated) >= 2:
                            all_paths.append(translated)

                    # Add hatch fill if filled mode
                    if render_mode == "filled" and glyph.paths:
                        hatch = hatch_fill(glyph.paths, pen_tip_mm)
                        for hatch_path in hatch:
                            translated = [(gx + px, gy + py) for px, py in hatch_path]
                            if len(translated) >= 2:
                                all_paths.append(translated)

                    cursor_x += glyph.advance

                # Add space between words
                cursor_x += space_width

            cursor_y += line_height

    # Phase 2: Optimize path ordering
    if optimize and all_paths:
        all_paths = _reorder_paths_nearest_neighbor(all_paths)
        all_paths = _merge_nearby_endpoints(all_paths, max(pen_tip_mm * 0.5, 0.1))

    # Phase 3: Emit operations and compute stats
    operations = []
    last_point = None
    draw_distance = 0
    travel_distance = 0
    draw_count = 0
    travel_count = 0
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for path in all_paths:
        for pt in path:
            min_x = min(min_x, pt[0])
            min_y = min(min_y, pt[1])
            max_x = max(max_x, pt[0])
            max_y = max(max_y, pt[1])

        # Travel to start of path
        start = path[0]
        if last_point and last_point != start:
            travel_pts = [list(last_point), list(start)]
            operations.append({"type": "travel", "points": travel_pts})
            travel_distance += _distance(last_point, start)
            travel_count += 1

        # Draw the path
        draw_pts = [list(pt) for pt in path]
        operations.append({"type": "draw", "points": draw_pts})
        draw_distance += _path_length(path)
        draw_count += 1
        last_point = path[-1]

    return {
        "mode": "write",
        "render_mode": render_mode,
        "pen_tip_mm": pen_tip_mm,
        "operations": operations,
        "paper": {"width": paper_w, "height": paper_h},
        "margins": margins,
        "bounds": {
            "min_x": round(min_x, 2) if min_x != float("inf") else 0,
            "min_y": round(min_y, 2) if min_y != float("inf") else 0,
            "max_x": round(max_x, 2) if max_x != float("-inf") else 0,
            "max_y": round(max_y, 2) if max_y != float("-inf") else 0,
        },
        "stats": {
            "draw_count": draw_count,
            "travel_count": travel_count,
            "draw_distance_mm": round(draw_distance, 1),
            "travel_distance_mm": round(travel_distance, 1),
        },
    }


def generate_braille_toolpath(
    text,
    language="en",
    grade=1,
    paper_size=(210, 297),
    margins=None,
    paper_offset=None,
    optimize=True,
):
    if margins is None:
        margins = dict(DEFAULT_MARGINS)
    if paper_offset is None:
        paper_offset = dict(PAPER_OFFSET)

    paper_w, paper_h = paper_size
    left = margins.get("left", 10)
    right = margins.get("right", 10)
    top = margins.get("top", 10)
    bottom = margins.get("bottom", 10)
    offset_x = paper_offset.get("x", 0)
    offset_y = paper_offset.get("y", 0)

    usable_width = paper_w - left - right

    cells = translate_to_braille(text, language, grade)

    # Split cells into words (empty cell = space)
    words = []
    current_word = []
    for cell in cells:
        if not cell:  # space
            if current_word:
                words.append(current_word)
                current_word = []
        else:
            current_word.append(cell)
    if current_word:
        words.append(current_word)

    # Word wrap braille
    wrapped_lines = []
    current_line = []
    current_width = 0

    for word in words:
        word_width = len(word) * BRAILLE_CELL_WIDTH
        if not current_line:
            current_line.append(word)
            current_width = word_width
        elif current_width + BRAILLE_WORD_GAP + word_width <= usable_width:
            current_line.append(word)
            current_width += BRAILLE_WORD_GAP + word_width
        else:
            wrapped_lines.append(current_line)
            current_line = [word]
            current_width = word_width

    if current_line:
        wrapped_lines.append(current_line)

    # Phase 1: Collect all dot positions
    all_dots = []
    cursor_y = top + offset_y

    for line_words in wrapped_lines:
        if cursor_y + BRAILLE_CELL_HEIGHT > paper_h - bottom + offset_y:
            break

        cursor_x = left + offset_x

        for word_idx, word in enumerate(line_words):
            if word_idx > 0:
                cursor_x += BRAILLE_WORD_GAP

            for cell in word:
                for dot in cell:
                    if dot == 1:
                        dx, dy = 0, 0
                    elif dot == 2:
                        dx, dy = 0, BRAILLE_DOT_SPACING
                    elif dot == 3:
                        dx, dy = 0, BRAILLE_DOT_SPACING * 2
                    elif dot == 4:
                        dx, dy = BRAILLE_DOT_SPACING, 0
                    elif dot == 5:
                        dx, dy = BRAILLE_DOT_SPACING, BRAILLE_DOT_SPACING
                    elif dot == 6:
                        dx, dy = BRAILLE_DOT_SPACING, BRAILLE_DOT_SPACING * 2
                    else:
                        continue

                    all_dots.append((cursor_x + dx, cursor_y + dy))

                cursor_x += BRAILLE_CELL_WIDTH

        cursor_y += BRAILLE_CELL_HEIGHT

    # Phase 2: Optimize dot ordering
    if optimize and all_dots:
        all_dots = _reorder_points_nearest_neighbor(all_dots)

    # Phase 3: Emit operations and compute stats
    operations = []
    last_point = None
    travel_distance = 0
    punch_count = 0
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for dot in all_dots:
        px, py = dot
        point = [px, py]

        min_x = min(min_x, px)
        min_y = min(min_y, py)
        max_x = max(max_x, px)
        max_y = max(max_y, py)

        # Travel to dot position
        if last_point:
            travel_pts = [list(last_point), point]
            operations.append({"type": "travel", "points": travel_pts})
            travel_distance += _distance(last_point, point)
        else:
            operations.append({"type": "travel", "points": [[0, 0], point]})
            travel_distance += _distance((0, 0), point)

        # Punch
        operations.append({"type": "punch", "point": point})
        punch_count += 1
        last_point = point

    return {
        "mode": "braille",
        "operations": operations,
        "paper": {"width": paper_w, "height": paper_h},
        "margins": margins,
        "bounds": {
            "min_x": round(min_x, 2) if min_x != float("inf") else 0,
            "min_y": round(min_y, 2) if min_y != float("inf") else 0,
            "max_x": round(max_x, 2) if max_x != float("-inf") else 0,
            "max_y": round(max_y, 2) if max_y != float("-inf") else 0,
        },
        "stats": {
            "punch_count": punch_count,
            "travel_distance_mm": round(travel_distance, 1),
        },
    }
