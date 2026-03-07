import hashlib
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests
import uharfbuzz as hb
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from scipy.spatial import Voronoi
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import linemerge, unary_union

from google_fonts import get_ttf_url

logger = logging.getLogger(__name__)

FONT_CACHE_DIR = Path("/tmp/font_cache")
FONT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Tolerance for flattening curves to polylines (in font units, scaled later)
CURVE_TOLERANCE = 10


@dataclass
class GlyphResult:
    char: str
    paths: list[list[tuple[float, float]]] = field(default_factory=list)
    x_offset: float = 0
    y_offset: float = 0
    advance: float = 0


def get_ttf_path(font_family: str) -> Path:
    safe_name = hashlib.md5(font_family.encode()).hexdigest()
    cached = FONT_CACHE_DIR / f"{safe_name}.ttf"
    if cached.exists():
        return cached

    url = get_ttf_url(font_family)
    if not url:
        raise ValueError(f"No TTF URL found for font '{font_family}'")

    logger.info("Downloading TTF for '%s'", font_family)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    cached.write_bytes(resp.content)
    return cached


def _flatten_quadratic(points, tolerance):
    """Flatten a quadratic B-spline segment to line segments."""
    if len(points) < 3:
        return list(points)

    result = [points[0]]
    for i in range(1, len(points) - 1, 2):
        if i + 1 >= len(points):
            result.append(points[i])
            break
        p0 = result[-1]
        p1 = points[i]
        p2 = points[i + 1]
        _subdivide_quadratic(p0, p1, p2, tolerance, result)
    return result


def _subdivide_quadratic(p0, p1, p2, tolerance, result):
    """Recursively subdivide a quadratic bezier until flat enough."""
    mid_x = (p0[0] + 2 * p1[0] + p2[0]) / 4
    mid_y = (p0[1] + 2 * p1[1] + p2[1]) / 4
    line_mid_x = (p0[0] + p2[0]) / 2
    line_mid_y = (p0[1] + p2[1]) / 2
    dist = math.hypot(mid_x - line_mid_x, mid_y - line_mid_y)

    if dist <= tolerance:
        result.append(p2)
    else:
        q0 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        q2 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        q1 = ((q0[0] + q2[0]) / 2, (q0[1] + q2[1]) / 2)
        _subdivide_quadratic(p0, q0, q1, tolerance, result)
        _subdivide_quadratic(q1, q2, p2, tolerance, result)


def _subdivide_cubic(p0, p1, p2, p3, tolerance, result):
    """Recursively subdivide a cubic bezier until flat enough."""
    # Check flatness: max deviation of control points from the line p0-p3
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    d = math.hypot(dx, dy)
    if d < 1e-10:
        result.append(p3)
        return

    d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) / d
    d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) / d

    if max(d1, d2) <= tolerance:
        result.append(p3)
    else:
        m01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        m12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        m23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)
        m012 = ((m01[0] + m12[0]) / 2, (m01[1] + m12[1]) / 2)
        m123 = ((m12[0] + m23[0]) / 2, (m12[1] + m23[1]) / 2)
        mid = ((m012[0] + m123[0]) / 2, (m012[1] + m123[1]) / 2)
        _subdivide_cubic(p0, m01, m012, mid, tolerance, result)
        _subdivide_cubic(mid, m123, m23, p3, tolerance, result)


def _recording_pen_to_paths(rec, tolerance):
    """Convert a RecordingPen's recorded operations to polyline paths."""
    paths = []
    current_path = []
    current_pt = (0, 0)

    for op, args in rec.value:
        if op == "moveTo":
            if len(current_path) > 1:
                paths.append(current_path)
            current_pt = args[0]
            current_path = [current_pt]

        elif op == "lineTo":
            current_pt = args[0]
            current_path.append(current_pt)

        elif op == "qCurveTo":
            pts = [current_pt] + list(args)
            flat = _flatten_quadratic(pts, tolerance)
            current_path.extend(flat[1:])
            current_pt = flat[-1]

        elif op == "curveTo":
            # Cubic bezier: args = (p1, p2, p3) where current_pt is p0
            pts = list(args)
            result = []
            _subdivide_cubic(current_pt, pts[0], pts[1], pts[2], tolerance, result)
            current_path.extend(result)
            current_pt = result[-1] if result else current_pt

        elif op == "closePath" or op == "endPath":
            if len(current_path) > 1:
                if op == "closePath" and current_path[0] != current_path[-1]:
                    current_path.append(current_path[0])
                paths.append(current_path)
            current_path = []

    if len(current_path) > 1:
        paths.append(current_path)

    return paths


def _shape_text(ttf_path, text):
    """Use HarfBuzz to shape text, returning glyph IDs and positions."""
    font_data = ttf_path.read_bytes()
    blob = hb.Blob(font_data)
    face = hb.Face(blob)
    font = hb.Font(face)
    font.scale = (face.upem, face.upem)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)

    infos = buf.glyph_infos
    positions = buf.glyph_positions

    return font, face, infos, positions


def get_font_metrics(ttf_path, font_size_mm):
    """Get font metrics scaled to mm."""
    ttf_path = Path(ttf_path)
    tt = TTFont(ttf_path)
    upem = tt["head"].unitsPerEm
    os2 = tt.get("OS/2")

    scale = font_size_mm / upem

    ascender = (os2.sTypoAscender if os2 else upem * 0.8) * scale
    descender = abs((os2.sTypoDescender if os2 else upem * -0.2) * scale)
    line_height = ascender + descender

    return {
        "line_height": line_height,
        "ascender": ascender,
        "descender": descender,
    }


def get_glyph_outlines(ttf_path, text, font_size_mm):
    """Extract glyph outlines as polylines in mm, using HarfBuzz for shaping."""
    ttf_path = Path(ttf_path)
    tt = TTFont(ttf_path)
    glyf_table = tt.get("glyf")
    cff_table = tt.get("CFF ")
    upem = tt["head"].unitsPerEm
    scale = font_size_mm / upem

    font, face, infos, positions = _shape_text(ttf_path, text)
    glyphset = tt.getGlyphSet()

    results = []

    for i, (info, pos) in enumerate(zip(infos, positions)):
        glyph_id = info.codepoint
        cluster = info.cluster
        char = text[cluster] if cluster < len(text) else ""

        glyph_name = tt.getGlyphName(glyph_id)
        # x_offset/y_offset are per-glyph HarfBuzz adjustments only (usually 0
        # for simple LTR). Cumulative positioning is handled by the caller via
        # the advance field.
        x_offset = pos.x_offset * scale
        y_offset = pos.y_offset * scale
        x_advance = pos.x_advance * scale

        paths = []
        if glyph_name and glyph_name in glyphset:
            pen = RecordingPen()
            glyphset[glyph_name].draw(pen)
            raw_paths = _recording_pen_to_paths(pen, CURVE_TOLERANCE)

            for raw_path in raw_paths:
                scaled = []
                for px, py in raw_path:
                    # Flip Y axis (font coords have Y up, we want Y down)
                    sx = px * scale
                    sy = -py * scale
                    scaled.append((sx, sy))
                if len(scaled) > 1:
                    paths.append(scaled)

        result = GlyphResult(
            char=char,
            paths=paths,
            x_offset=x_offset,
            y_offset=y_offset,
            advance=x_advance,
        )
        results.append(result)

    return results


def _paths_to_fill_shape(outline_paths):
    """Convert glyph outline paths to a Shapely geometry with proper holes.

    Uses containment: largest contours are outer boundaries, smaller contours
    contained within them are holes (e.g., the hole in 'o', 'e', 'd', 'b').
    """
    polygons = []
    for path in outline_paths:
        if len(path) >= 4:
            pts = list(path)
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            try:
                poly = Polygon(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty and poly.area > 0:
                    polygons.append(poly)
            except Exception:
                continue

    if not polygons:
        return None

    # Sort largest first — outer contours have larger area than holes
    polygons.sort(key=lambda p: p.area, reverse=True)

    # Build polygon hierarchy: for each polygon, check if it's a hole inside
    # a larger polygon. If so, reconstruct the outer polygon with that hole.
    used = [False] * len(polygons)
    result_polys = []

    for i, outer in enumerate(polygons):
        if used[i]:
            continue
        # Find all smaller polygons contained within this one — those are holes
        holes = []
        for j in range(i + 1, len(polygons)):
            if used[j]:
                continue
            inner = polygons[j]
            try:
                if outer.contains(inner):
                    holes.append(inner.exterior.coords)
                    used[j] = True
            except Exception:
                continue

        try:
            if holes:
                poly_with_holes = Polygon(outer.exterior.coords, holes)
                if not poly_with_holes.is_valid:
                    poly_with_holes = poly_with_holes.buffer(0)
                if not poly_with_holes.is_empty:
                    result_polys.append(poly_with_holes)
            else:
                result_polys.append(outer)
        except Exception:
            result_polys.append(outer)

    if not result_polys:
        return None

    if len(result_polys) == 1:
        return result_polys[0]

    try:
        from shapely.ops import unary_union
        combined = unary_union(result_polys)
        return combined if not combined.is_empty else None
    except Exception:
        return result_polys[0]


def hatch_fill(outline_paths, pen_tip_mm, angle_deg=45):
    """Generate parallel hatch lines filling the interior of outline paths.

    Args:
        outline_paths: list of polyline paths (each a list of (x,y) tuples)
        pen_tip_mm: spacing between hatch lines
        angle_deg: angle of hatch lines in degrees

    Returns:
        List of polyline segments (each a list of (x,y) tuples)
    """
    if not outline_paths:
        return []

    combined = _paths_to_fill_shape(outline_paths)
    if combined is None:
        return []

    if combined.is_empty:
        return []

    # Ensure we have a list of polygons
    if isinstance(combined, Polygon):
        polys = [combined]
    elif isinstance(combined, MultiPolygon):
        polys = list(combined.geoms)
    else:
        return []

    # Get bounds
    minx, miny, maxx, maxy = combined.bounds
    diagonal = math.hypot(maxx - minx, maxy - miny)

    # Generate hatch lines
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    spacing = max(pen_tip_mm, 0.1)

    hatch_lines = []
    n_lines = int(diagonal / spacing) + 2
    center_x = (minx + maxx) / 2
    center_y = (miny + maxy) / 2

    for i in range(-n_lines, n_lines + 1):
        offset = i * spacing
        # Line perpendicular direction offset, along the angle
        px = center_x + offset * (-sin_a)
        py = center_y + offset * cos_a
        # Line endpoints extending beyond bounds
        x1 = px - diagonal * cos_a
        y1 = py - diagonal * sin_a
        x2 = px + diagonal * cos_a
        y2 = py + diagonal * sin_a

        line = LineString([(x1, y1), (x2, y2)])

        for poly in polys:
            intersection = poly.intersection(line)
            if intersection.is_empty:
                continue
            if intersection.geom_type == "LineString":
                coords = list(intersection.coords)
                if len(coords) >= 2:
                    hatch_lines.append([(x, y) for x, y in coords])
            elif intersection.geom_type == "MultiLineString":
                for seg in intersection.geoms:
                    coords = list(seg.coords)
                    if len(coords) >= 2:
                        hatch_lines.append([(x, y) for x, y in coords])

    return hatch_lines


def _sample_ring(ring, spacing):
    """Densely sample points along a ring (LinearRing)."""
    length = ring.length
    if length == 0:
        return []
    n = max(int(length / spacing), 20)
    return [(ring.interpolate(i * length / n).x, ring.interpolate(i * length / n).y) for i in range(n)]


def centerline_from_outline(outline_paths):
    """Extract centerline paths from glyph outline paths using Voronoi medial axis.

    Uses distance-from-boundary filtering to remove noisy edges near the outline,
    keeping only the true medial axis (skeleton) of the glyph shape.
    """
    if not outline_paths:
        return []

    combined = _paths_to_fill_shape(outline_paths)
    if combined is None:
        return []

    if isinstance(combined, Polygon):
        polys = [combined]
    elif isinstance(combined, MultiPolygon):
        polys = list(combined.geoms)
    else:
        return []

    all_centerlines = []

    for poly in polys:
        # Estimate stroke width from area/perimeter ratio
        # For a stroke of width w and length L: area ~ w*L, perimeter ~ 2*L + 2*w
        # So w ~ 2*area / perimeter (approximate)
        area = poly.area
        perimeter = poly.exterior.length
        if perimeter == 0:
            continue
        estimated_stroke_width = 2 * area / perimeter

        # Sample spacing relative to stroke width — finer sampling = better Voronoi
        sample_spacing = max(estimated_stroke_width * 0.15, 0.02)

        # Sample boundary
        boundary_points = _sample_ring(poly.exterior, sample_spacing)
        for ring in poly.interiors:
            boundary_points.extend(_sample_ring(ring, sample_spacing))

        if len(boundary_points) < 6:
            continue

        points_array = np.array(boundary_points)
        try:
            vor = Voronoi(points_array)
        except Exception:
            continue

        # Distance threshold: keep edges where both endpoints are at least
        # this far from the boundary. This filters out the noisy edges that
        # hug the outline. Use a fraction of the estimated stroke width.
        min_dist = estimated_stroke_width * 0.2
        boundary_line = poly.exterior

        # Pre-compute vertex distances from boundary
        vertex_dists = {}

        def _vert_dist(vi):
            if vi not in vertex_dists:
                v = vor.vertices[vi]
                vertex_dists[vi] = boundary_line.distance(Point(v[0], v[1]))
            return vertex_dists[vi]

        # Filter edges: inside polygon, both endpoints far enough from boundary,
        # and edge not too short
        min_edge_len = estimated_stroke_width * 0.1
        interior_edges = []

        for v1, v2 in vor.ridge_vertices:
            if v1 < 0 or v2 < 0:
                continue

            p1 = vor.vertices[v1]
            p2 = vor.vertices[v2]

            # Skip very short edges (noise)
            edge_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if edge_len < min_edge_len:
                continue

            # Both endpoints must be inside the polygon
            pt1 = Point(p1[0], p1[1])
            pt2 = Point(p2[0], p2[1])
            if not (poly.contains(pt1) and poly.contains(pt2)):
                continue

            # Both endpoints must be sufficiently far from the boundary
            d1 = _vert_dist(v1)
            d2 = _vert_dist(v2)
            if d1 < min_dist or d2 < min_dist:
                continue

            interior_edges.append(((p1[0], p1[1]), (p2[0], p2[1])))

        if not interior_edges:
            continue

        # Merge connected edges into polylines
        lines = [LineString([e[0], e[1]]) for e in interior_edges]
        try:
            merged = linemerge(lines)
        except Exception:
            for edge in interior_edges:
                all_centerlines.append([edge[0], edge[1]])
            continue

        if isinstance(merged, LineString):
            coords = list(merged.coords)
            if len(coords) >= 2:
                all_centerlines.append([(x, y) for x, y in coords])
        elif isinstance(merged, MultiLineString):
            for line in merged.geoms:
                coords = list(line.coords)
                if len(coords) >= 2:
                    all_centerlines.append([(x, y) for x, y in coords])

    return all_centerlines


def get_glyph_centerlines(ttf_path, text, font_size_mm):
    """Extract single-stroke centerlines for glyphs using Voronoi medial axis.

    Same interface as get_glyph_outlines but returns centerline paths instead.
    """
    # First get the outlines (we need them to compute centerlines)
    glyphs = get_glyph_outlines(ttf_path, text, font_size_mm)

    # For each glyph, compute centerlines from its outline paths
    for glyph in glyphs:
        if glyph.paths:
            centerlines = centerline_from_outline(glyph.paths)
            if centerlines:
                glyph.paths = centerlines
            # If centerline extraction fails, keep the outlines as fallback

    return glyphs


# ── Hershey Fonts ──

# Map of user-facing names to HersheyFonts internal font names
HERSHEY_FONTS = {
    "Hershey Sans": "futural",
    "Hershey Sans Bold": "futuram",
    "Hershey Serif": "rowmans",
    "Hershey Serif Bold": "rowmand",
    "Hershey Script": "scripts",
    "Hershey Script Bold": "scriptc",
    "Hershey Cursive": "cursive",
    "Hershey Gothic English": "gothiceng",
    "Hershey Gothic German": "gothicger",
    "Hershey Gothic Italian": "gothicita",
}


def is_hershey_font(font_family):
    return font_family in HERSHEY_FONTS


def list_hershey_fonts():
    return list(HERSHEY_FONTS.keys())


def get_hershey_glyphs(font_family, text, font_size_mm):
    """Render text using a Hershey vector font, returning GlyphResult objects.

    Hershey fonts are single-stroke — each path is already a centerline, perfect
    for pen plotters. ASCII only.
    """
    from HersheyFonts import HersheyFonts

    internal_name = HERSHEY_FONTS.get(font_family, "futural")

    hf = HersheyFonts()
    hf.load_default_font(internal_name)
    # normalize_rendering sets the target height in arbitrary units;
    # we'll use 1000 as the rendering height and scale to mm afterward
    render_height = 1000
    hf.normalize_rendering(render_height)
    scale = font_size_mm / render_height

    results = []

    # Process character by character to get per-glyph data
    cursor_x = 0
    for char in text:
        # Get strokes for this single character
        char_strokes = list(hf.strokes_for_text(char))

        # Measure advance: render char and find the rightmost x
        all_points = []
        for stroke in char_strokes:
            all_points.extend(stroke)

        if all_points:
            min_x = min(p[0] for p in all_points)
            max_x = max(p[0] for p in all_points)
            char_width = (max_x - min_x) * scale
            char_left = min_x * scale
        else:
            # Space or unsupported character
            char_width = font_size_mm * 0.4
            char_left = 0

        paths = []
        for stroke in char_strokes:
            if len(stroke) >= 2:
                # Scale and shift so glyph origin is at left edge
                path = [((x * scale) - char_left, -y * scale) for x, y in stroke]
                paths.append(path)

        advance = char_width + font_size_mm * 0.05  # small inter-char gap

        result = GlyphResult(
            char=char,
            paths=paths,
            x_offset=0,
            y_offset=0,
            advance=advance,
        )
        results.append(result)

    return results


def get_hershey_metrics(font_family, font_size_mm):
    """Get approximate font metrics for a Hershey font."""
    # Hershey fonts have roughly these proportions
    return {
        "line_height": font_size_mm * 1.4,
        "ascender": font_size_mm * 0.9,
        "descender": font_size_mm * 0.5,
    }
