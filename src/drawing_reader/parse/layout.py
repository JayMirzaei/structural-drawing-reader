"""Geometry helpers on text runs, and where the title block sits on a sheet.

Everything here works on the primitives from ingestion (runs, segments, rectangles) and assumes no
sheet-specific coordinates.
"""

from __future__ import annotations

from drawing_reader.ingest import Sheet, TextRun


def is_horizontal(r: TextRun) -> bool:
    return abs(r.dir[1]) < 0.05 and r.dir[0] > 0


def same_row(a: TextRun, b: TextRun, tol: float | None = None) -> bool:
    tol = tol or max(3.0, 0.4 * min(a.size, b.size))
    return abs(a.bbox[1] - b.bbox[1]) <= tol or abs(a.center[1] - b.center[1]) <= tol


def x_overlap(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def run_orientation(r: TextRun) -> str:
    ang = abs(r.angle) % 180
    if ang < 8 or ang > 172:
        return "horizontal"
    if 82 < ang < 98:
        return "vertical"
    return "diagonal"


def bottom_band_y(sheet: Sheet) -> float:
    """y above which the title block lives. Assumes a bottom title strip (most N. American sheets)."""
    return sheet.height * 0.82


def _strip_divider_x(sheet: Sheet) -> float | None:
    """x of a right-hand title-block strip's vertical divider, if this sheet uses that convention
    instead of a bottom strip: a vertical line -- one or more collinear `segments`, or a thin tall
    `rects` entry (width < 2pt) -- between 0.75W and 0.96W with total vertical extent >= 0.6H, and
    at least 5 text runs to its right (otherwise a bare vertical line isn't a title-block divider).
    None if no such divider is found, meaning this sheet uses the bottom-strip convention."""
    w, h = sheet.width, sheet.height
    lo, hi = 0.75 * w, 0.96 * w
    spans: dict[float, list[tuple[float, float]]] = {}
    for seg in sheet.segments:
        x0, y0 = seg.p1
        x1, y1 = seg.p2
        if abs(x0 - x1) > 2:  # not vertical
            continue
        x = round((x0 + x1) / 2)
        if lo < x < hi:
            spans.setdefault(x, []).append((min(y0, y1), max(y0, y1)))
    for rx0, ry0, rx1, ry1 in sheet.rects:
        if rx1 - rx0 >= 2:  # not thin enough to be a rule line
            continue
        x = round((rx0 + rx1) / 2)
        if lo < x < hi:
            spans.setdefault(x, []).append((min(ry0, ry1), max(ry0, ry1)))
    for x, pieces in spans.items():
        if _covered_length(pieces) >= 0.6 * h and sum(1 for r in sheet.runs if r.bbox[0] >= x) >= 5:
            return x
    return None


def _covered_length(pieces: list[tuple[float, float]]) -> float:
    """Length of the union of 1-D intervals. Lines drawn over one another (a column on its grid line,
    in an elevation near the sheet's right edge) count once, so they cannot add up to a divider."""
    total, end = 0.0, float("-inf")
    for lo, hi in sorted(pieces):
        if hi > end:
            total += hi - max(lo, end)
            end = hi
    return total


def titleblock_runs(sheet: Sheet) -> list[TextRun]:
    """Which runs belong to the title block rather than the drawing area, under either drafting
    convention. Bottom strip (most N. American sheets): everything at/below `bottom_band_y` is title
    block. Right-hand strip (a less common layout): only the runs both right of the strip's
    vertical divider *and* at/below the band are title block -- drawing-area text that happens to
    fall in the bottom band (a view title, a scale note) stays out, and title-block text above the
    band (a revision table, consultant stack) that already isn't in the band is unaffected either
    way.

    Known limit: some templates put real title-block content (a Client field, say) higher up the
    right-hand strip than the bottom band. Dropping the band restriction for that case was tried and
    reverted: the vertical-line detection in `_strip_divider_x` does not guarantee that the divider
    separates drawing area from title block on every template, and the wider scope picked up
    drawing-area text (sheet titles came back as "No."). It needs a more targeted fix than widening
    this shared function."""
    band = bottom_band_y(sheet)
    x = _strip_divider_x(sheet)
    if x is None and sheet.titleblock_x is not None:
        # scan: the title-block box found in the raster; drawing text left of it stays in the body
        # a big number in the box's top cell can straddle the band line: a run belongs to the block when its centre is
        # in the band
        return [r for r in sheet.runs if r.bbox[0] >= sheet.titleblock_x and r.center[1] >= band]
    if x is None:
        return [r for r in sheet.runs if r.bbox[1] >= band]
    return [r for r in sheet.runs if r.bbox[0] >= x and r.bbox[1] >= band]
