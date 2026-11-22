"""Text recognition passes: whole page, tiled at scan resolution, and rotated for vertical text.

The engine is RapidOCR (detection and recognition CNNs run through onnxruntime, CPU only, offline).
It is an optional dependency; `available()` says whether it is installed.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pymupdf

from drawing_reader.ocr import config
from drawing_reader.ocr.raster import native_scale
from drawing_reader.ocr.runs import fix_vertical, group_blocks, iou

_engine = None


# A scale ratio's colon is often read as ";" / "|" / "!" ("1; 2.5"): put the colon back. A "." is left alone
# (it is a decimal point elsewhere), and only a whole-run ratio is touched.
_RE_RATIO_MISREAD = re.compile(r"^(\d{1,2})\s*[;|!]\s*(\d+(?:\.\d+)?)$")


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return True
    except ImportError:
        return False


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def ocr_page(page: pymupdf.Page, page_idx: int, run_cls) -> list:
    """OCR one page; returns `run_cls` (ingest.TextRun) objects in the page's displayed point space."""
    scale = min(config.OCR_MAX_PX / max(page.rect.width, page.rect.height), 200 / 72)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    res, _ = _get_engine()(np.stack([img] * 3, axis=-1))
    runs = []
    for box, text, conf in res or []:
        conf = float(conf)
        text = text.strip()
        if not text or conf < config.MIN_RUN_CONF:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        (x0, y0), (x1, y1) = box[0], box[1]
        ang = math.atan2(y1 - y0, x1 - x0)
        h = math.hypot(box[3][0] - box[0][0], box[3][1] - box[0][1])
        if not _keep_angle(ang, conf):
            continue
        text = _RE_RATIO_MISREAD.sub(r"\1:\2", text)
        n = len(runs) + 1
        runs.append(
            run_cls(
                id=f"p{page_idx + 1}.t{n:03d}",
                text=text,
                bbox=tuple(round(v / scale, 1) for v in (min(xs), min(ys), max(xs), max(ys))),
                dir=_dir_of(ang),
                size=round(h / scale, 1),
                block=n,
                conf=round(conf, 2),
            )
        )
    fix_vertical(runs)
    group_blocks(runs)
    return runs


def _keep_angle(ang: float, conf: float) -> bool:
    """Which recognitions to keep by the angle of their box (radians, image coordinates). Upright text (within 15
    degrees) always; text at an angle (15-75 degrees: a diagonal member's label, an angle value) only when the engine
    is confident (0.9+), since a wrong rotation reads as garbage but a right one reads cleanly; near-vertical oriented
    boxes are left to the vertical handling."""
    a = abs(math.degrees(ang))
    return a <= 15 or (15 < a < 75 and conf >= 0.9)


def _dir_of(ang: float) -> tuple[float, float]:
    """Reading direction (page coordinates, y down) of a box at this angle; exactly (1, 0) for upright text."""
    return (1.0, 0.0) if abs(math.degrees(ang)) <= 15 else (round(math.cos(ang), 3), round(math.sin(ang), 3))


def _tile_boxes(img: np.ndarray, stats: dict | None = None):
    """(box points, text, conf) for every recognition of a grey image read in tiles of at most config.TILE_PX,
    overlapping by config.TILE_OVERLAP, so each tile reaches the detector at its own resolution (it shrinks anything
    over 2000 px on the long side). A box touching an interior tile edge is dropped: the next tile, overlapping, reads
    it whole. Blank tiles are skipped. `stats`, if given, gets the number of tiles the grid has ("grid") and how many
    were read ("read")."""
    H, W = img.shape
    step = config.TILE_PX - config.TILE_OVERLAP
    for y in range(0, max(1, H - config.TILE_OVERLAP), step):
        for x in range(0, max(1, W - config.TILE_OVERLAP), step):
            tile = img[y : y + config.TILE_PX, x : x + config.TILE_PX]
            th, tw = tile.shape
            if stats is not None:
                stats["grid"] = stats.get("grid", 0) + 1
            # a sliver, blank paper, or a tile with next to no ink
            if th < 40 or tw < 40 or tile.min() > 200 or (tile < 128).mean() < 0.002:
                continue
            if stats is not None:
                stats["read"] = stats.get("read", 0) + 1
            res, _ = _get_engine()(np.stack([tile] * 3, axis=-1))
            for box, text, conf in res or []:
                conf, text = float(conf), text.strip()
                if not text or conf < config.MIN_RUN_CONF:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                if (
                    (x > 0 and min(xs) <= 2)
                    or (x + tw < W and max(xs) >= tw - 2)
                    or (y > 0 and min(ys) <= 2)
                    or (y + th < H and max(ys) >= th - 2)
                ):
                    continue
                yield [(px + x, py + y) for px, py in box], text, conf


def _tile_image(page: pymupdf.Page, text_pt: float | None = None):
    want = config.TILE_TEXT_PX / text_pt if text_pt else config.TILE_SCALE
    s = min(max(1.0, want), native_scale(page), config.OCR_MAX_PX / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(s, s), colorspace=pymupdf.csGRAY)
    return s, np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def text_height_pt(runs: list) -> float | None:
    """Typical lettering height of a page in points, from the first pass: the median box height of its confident runs
    of 3+ characters, less the ~30% an OCR box pads it by. None when there are too few runs to say."""
    h = sorted(r.size for r in runs if r.conf >= 0.8 and len(r.text.strip()) >= 3 and tuple(r.dir) == (1.0, 0.0))
    return round(0.7 * h[len(h) // 2], 2) if len(h) >= 8 else None


def ocr_tiled(page: pymupdf.Page, page_idx: int, run_cls, text_pt: float | None = None) -> tuple[list, dict]:
    """The page read tile by tile at about its scan resolution (see `_tile_boxes`): the small lettering of a big
    drawing, dimensions above all, that the first pass loses when the detector shrinks the whole page. Runs come back
    in page points, to be combined with the first pass by `merge_runs`."""
    s, img = _tile_image(page, text_pt)
    runs = []
    stats: dict = {}
    for box, text, conf in _tile_boxes(img, stats):
        (x0, y0), (x1, y1) = box[0], box[1]
        ang = math.atan2(y1 - y0, x1 - x0)
        if not _keep_angle(ang, conf):
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        h = math.hypot(box[3][0] - box[0][0], box[3][1] - box[0][1])
        n = len(runs) + 1
        runs.append(
            run_cls(
                id=f"p{page_idx + 1}.u{n:04d}",
                text=_RE_RATIO_MISREAD.sub(r"\1:\2", text),
                bbox=tuple(round(v / s, 1) for v in (min(xs), min(ys), max(xs), max(ys))),
                dir=_dir_of(ang),
                size=round(h / s, 1),
                block=n,
                conf=round(conf, 2),
            )
        )
    return runs, dict(tiles=stats.get("read", 0), grid=stats.get("grid", 0), scale=round(s, 2), text_pt=text_pt or 0.0)


def ocr_vertical(
    page: pymupdf.Page, page_idx: int, run_cls, known: list, text_pt: float | None = None
) -> tuple[list, dict]:
    """Text running up the page (vertical dimensions, column labels) that the other passes missed: the page raster
    turned 90 degrees clockwise puts such text horizontal, where the detector and recogniser are reliable, and is read
    tile by tile like `ocr_tiled`. Runs come back in page points with direction up (0, -1) and size = the short side,
    skipping any that overlap a run in `known` (IoU > 0.3), low-confidence ones (< 0.7), and boxes that are not tall
    in page space (horizontal text, turned vertical by the rotation, only produces noise here)."""
    s, img = _tile_image(page, text_pt)
    H = img.shape[0]
    rot = np.ascontiguousarray(np.rot90(img, k=-1))  # clockwise: rot[i, j] = img[H-1-j, i]
    runs = []
    stats: dict = {}
    for box, text, conf in _tile_boxes(rot, stats):
        if conf < 0.7 or len(text) < 2:
            continue
        (x0, y0), (x1, y1) = box[0], box[1]
        if abs(math.degrees(math.atan2(y1 - y0, x1 - x0))) > 15:
            continue
        pts = [(yr, H - 1 - xr) for xr, yr in box]  # rotated (xr, yr) -> page pixel (x = yr, y = H-1-xr)
        bx = (
            min(p[0] for p in pts) / s,
            min(p[1] for p in pts) / s,
            max(p[0] for p in pts) / s,
            max(p[1] for p in pts) / s,
        )
        w, h = bx[2] - bx[0], bx[3] - bx[1]
        if h < 1.5 * w or any(iou(bx, k.bbox) > 0.3 for k in known):
            continue
        n = len(runs) + 1
        runs.append(
            run_cls(
                id=f"p{page_idx + 1}.v{n:03d}",
                text=_RE_RATIO_MISREAD.sub(r"\1:\2", text),
                bbox=tuple(round(v, 1) for v in bx),
                dir=(0.0, -1.0),
                size=round(w, 1),
                block=10000 + n,
                conf=round(conf, 2),
            )
        )
    return runs, dict(tiles=stats.get("read", 0), grid=stats.get("grid", 0), scale=round(s, 2))
