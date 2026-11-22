"""What the page raster says besides text: is it a scan, where is the title block, where are the lines."""

from __future__ import annotations

import math

import numpy as np
import pymupdf

from drawing_reader.ocr import config


def is_scanned_page(page: pymupdf.Page) -> bool:
    """A page whose text must be read from pixels: no usable text layer, and the page is either mostly
    one image (a scan) or full of line art (CAD export with the lettering converted to outlines)."""
    area = page.rect.width * page.rect.height
    covered = sum(r.width * r.height for img in page.get_images(full=True) for r in page.get_image_rects(img[0]))
    if covered > 0.5 * area:
        return True
    return len(page.get_cdrawings()) >= config.OUTLINED_MIN_PATHS


def titleblock_left_x(page: pymupdf.Page) -> float | None:
    """x (points) of the left edge of a bottom-right title-block box, read from the raster.

    Convention: a scan has no vector lines, so the divider search in `parse.layout` cannot find the title block. The
    box's left edge is a long vertical ink line in the bottom 30% of the page: the leftmost column (right of 40% of
    the width: the box is a bottom-right one) whose longest vertical dark run is 120-400 pt (shorter is drawing
    detail, longer is the sheet frame) and ends within 250 pt of the page bottom. None when no such line is found."""
    w, h = page.rect.width, page.rect.height
    sc = 0.5
    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(sc, sc), clip=pymupdf.Rect(0, 0.70 * h, w, h), colorspace=pymupdf.csGRAY
    )
    ink = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width) < 128
    run = np.zeros(ink.shape[1], int)
    ending = np.zeros(ink.shape[1], int)  # longest ink run that ends within 250 pt of the page bottom
    first = ink.shape[0] - int(250 * sc)
    for i, row in enumerate(ink):
        run = (run + 1) * row
        if i >= first:
            ending = np.maximum(ending, run)
    # the box sits on the sheet's bottom border, so its left edge is a run ending there
    for x in range(int(0.4 * ink.shape[1]), ink.shape[1]):
        if 120 <= ending[x] / sc <= 400:
            return round(x / sc, 1)
    return None


def raster_segments(page: pymupdf.Page, seg_cls) -> list:
    """Long thin horizontal and vertical lines found in the page raster, as `seg_cls` segments in page points -- for a
    scan, which has no vector geometry, so dimension lines and other line rules have something to look at. A run of
    dark pixels at least ~12 pt long and a few pixels thick (morphological opening with a 1-pixel-high / 1-pixel-wide
    bar); broken (dashed) lines come out as pieces. The longest `SEG_MAX` are kept, so a table-heavy page does not
    drown the parsers."""
    import cv2

    # the scan's own resolution: a thin line is under a pixel at less
    s = min(native_scale(page, cap=3.0), 6000 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(s, s), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    _, bw = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = max(10, int(round(12 * s)))
    out = []
    for horizontal in (True, False):
        ker = cv2.getStructuringElement(cv2.MORPH_RECT, (k, 1) if horizontal else (1, k))
        op = cv2.morphologyEx(bw, cv2.MORPH_OPEN, ker)
        n, _, st, _ = cv2.connectedComponentsWithStats(op, connectivity=8)
        for x, y, w, h, _area in st[1:]:
            long_, thick = (w, h) if horizontal else (h, w)
            if long_ < k or thick > 6:
                continue
            if horizontal:
                p1, p2 = (x / s, (y + h / 2) / s), ((x + w) / s, (y + h / 2) / s)
            else:
                p1, p2 = ((x + w / 2) / s, y / s), ((x + w / 2) / s, (y + h) / s)
            out.append(
                seg_cls(
                    p1=(round(p1[0], 1), round(p1[1], 1)),
                    p2=(round(p2[0], 1), round(p2[1], 1)),
                    width=round(thick / s, 2),
                    dashed=False,
                )
            )
    out.sort(key=lambda g: -math.dist(g.p1, g.p2))
    return out[: config.SEG_MAX]


def native_scale(page: pymupdf.Page, cap: float = config.TILE_NATIVE_CAP) -> float:
    """Pixels per page point of the scan under the page: the largest embedded image's pixel width over the width it is
    placed at (a page with no image, such as a CAD export with outlined lettering, gets config.TILE_SCALE). Reading
    finer than the scan itself gains nothing."""
    best = 0.0
    try:
        for info in page.get_image_info():
            w = info["bbox"][2] - info["bbox"][0]
            if w > 0.5 * page.rect.width:
                best = max(best, info["width"] / w)
    except Exception:  # noqa: BLE001
        pass
    return min(cap, max(1.0, best)) if best else min(config.TILE_SCALE, cap)
