"""Extraction from a vector PDF page: text runs with their rotation, and line geometry."""

from __future__ import annotations

import pymupdf

from drawing_reader.ingest.primitives import Circle, Segment, TextRun


def _transform_bbox(bbox: tuple[float, float, float, float], m: pymupdf.Matrix) -> tuple[float, float, float, float]:
    """Map an axis-aligned bbox through an affine transform by transforming all four corners and
    re-deriving the axis-aligned box -- a plain rotation can swap which corner is min/max."""
    x0, y0, x1, y1 = bbox
    pts = [pymupdf.Point(x, y) * m for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _rotate_vector(v: tuple[float, float], m: pymupdf.Matrix) -> tuple[float, float]:
    """Apply only the linear (rotation) part of an affine transform to a direction vector -- a
    vector has no position, so the matrix's translation (e, f) must not be applied to it."""
    dx, dy = v
    return (dx * m.a + dy * m.c, dx * m.b + dy * m.d)


def decode_symbol_font(text: str) -> str:
    """Convention: text set in a symbol-encoded font (Word / CAD export, "Wingdings"-style mapping) arrives as
    private-use characters U+F020..U+F0FF, each the ASCII code plus 0xF000 ("\uf053\uf043\uf041\uf04c\uf045" is
    "SCALE"). When most of a line is such characters it is decoded; a line with only a stray symbol (a bullet) is left
    as read."""
    pua = sum(1 for c in text if 0xF020 <= ord(c) <= 0xF0FF)
    if pua and pua >= 0.5 * len(text.replace(" ", "")):
        return "".join(chr(ord(c) - 0xF000) if 0xF020 <= ord(c) <= 0xF07E else c for c in text).strip()
    return text


def _is_letter_spaced(text: str) -> bool:
    """Tracked-out lettering ("G E N E R A L N O T E S"): most of a longish line's tokens are single characters."""
    toks = text.split()
    return len(toks) >= 4 and sum(len(t) <= 2 for t in toks) >= 0.8 * len(toks) and sum(c.isalpha() for c in text) >= 4


def _despace_line(line: dict) -> str:
    """Convention: a CAD plot with wide letter tracking writes a space between every pair of letters, so a word break
    is only a slightly wider gap. The letters are re-joined, and a break is put where the gap between two letters is
    over 1.5x the line's median gap (a title's remaining run-together words are split later, by vocabulary)."""
    chars = [c for s in line["spans"] for c in s["chars"] if c["c"].strip()]
    if len(chars) < 4:
        return ""
    gaps = [chars[i + 1]["bbox"][0] - chars[i]["bbox"][2] for i in range(len(chars) - 1)]
    med = sorted(gaps)[len(gaps) // 2]
    if med > line["spans"][0]["size"]:
        return ""  # letters that far apart are separate marks (grid bubbles in a row), not tracked-out lettering
    out = [chars[0]["c"]]
    for g, c in zip(gaps, chars[1:], strict=False):
        if med > 0 and g > 1.5 * med:
            out.append(" ")
        out.append(c["c"])
    return "".join(out)


def extract_runs(page: pymupdf.Page, page_idx: int) -> list[TextRun]:
    """Convention: `page.get_text()`/`page.get_drawings()` both return coordinates in the page's
    raw, unrotated mediabox space, while `page.rect` (this app's Sheet.width/height) and the
    rendered pixmap already reflect the page's /Rotate value -- on a rotated page (any non-zero
    rotation, e.g. a landscape sheet plotted as a rotated portrait PDF page) those two spaces
    disagree, so every extracted primitive must go through `page.rotation_matrix` (identity when
    rotation is 0) to land in the same "as displayed" space everything downstream assumes."""
    runs: list[TextRun] = []
    rot = page.rotation_matrix
    td = page.get_text("dict")
    raw = None
    n = 0
    for bi, b in enumerate(td["blocks"]):
        if b.get("type") != 0:
            continue
        for li, line in enumerate(b["lines"]):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            if _is_letter_spaced(text):
                if raw is None:
                    raw = page.get_text("rawdict")["blocks"]
                try:
                    text = _despace_line(raw[bi]["lines"][li]) or text
                except (IndexError, KeyError):
                    pass
            n += 1
            runs.append(
                TextRun(
                    id=f"p{page_idx + 1}.t{n:03d}",
                    text=decode_symbol_font(text),
                    bbox=tuple(round(v, 1) for v in _transform_bbox(line["bbox"], rot)),
                    dir=tuple(round(v, 3) for v in _rotate_vector(line["dir"], rot)),
                    size=round(line["spans"][0]["size"], 1),
                    block=bi,
                )
            )
    return runs


def extract_geometry(page: pymupdf.Page) -> tuple[list[Segment], list[Circle], list[tuple]]:
    """See `extract_runs`' docstring -- `get_drawings()` is in the same raw, unrotated space and
    needs the same `page.rotation_matrix` correction."""
    rot = page.rotation_matrix
    segments, circles, rects = [], [], []
    for path in page.get_drawings():
        kinds = {it[0] for it in path["items"]}
        width = float(path.get("width") or 0)
        dashed = bool(path.get("dashes") and path["dashes"] not in ("[] 0", "", None))
        if kinds == {"c"}:
            r = path["rect"]
            bbox = _transform_bbox((r.x0, r.y0, r.x1, r.y1), rot)
            circles.append(Circle(bbox=tuple(round(v, 1) for v in bbox), arcs=len(path["items"]), width=width))
            continue
        for it in path["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                pa, pb = pymupdf.Point(a.x, a.y) * rot, pymupdf.Point(b.x, b.y) * rot
                segments.append(
                    Segment((round(pa.x, 1), round(pa.y, 1)), (round(pb.x, 1), round(pb.y, 1)), width, dashed)
                )
            elif it[0] == "re":
                r = it[1]
                bbox = _transform_bbox((r.x0, r.y0, r.x1, r.y1), rot)
                rects.append(tuple(round(v, 1) for v in bbox))
    return segments, circles, rects
