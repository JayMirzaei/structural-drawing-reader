"""The primitives every parser works on: text runs, line segments, circles, sheets.

A vector PDF gives these exactly; the OCR path produces the same objects from a scan, so nothing
above ingestion needs to know which kind of PDF it is reading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from drawing_reader.ingest.rendering import RENDER_DPI


@dataclass
class TextRun:
    id: str
    text: str
    bbox: tuple[float, float, float, float]  # PDF points, origin top-left
    dir: tuple[float, float]  # writing direction (dx, dy), y down
    size: float  # font size in points
    block: int  # pymupdf block index (paragraph grouping)
    conf: float = 1.0  # 1.0 for vector text; OCR engine confidence for scans

    @property
    def angle(self) -> float:
        """Text rotation in degrees, counter-clockwise, 0 = normal horizontal text."""
        return round(math.degrees(math.atan2(-self.dir[1], self.dir[0])), 1)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


@dataclass
class Segment:
    p1: tuple[float, float]
    p2: tuple[float, float]
    width: float
    dashed: bool

    @property
    def length(self) -> float:
        return math.dist(self.p1, self.p2)


@dataclass
class Circle:
    bbox: tuple[float, float, float, float]
    arcs: int  # 4 = full circle, 2 = half circle, 1 = quarter
    width: float

    @property
    def diameter(self) -> float:
        return max(self.bbox[2] - self.bbox[0], self.bbox[3] - self.bbox[1])

    @property
    def center(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)


@dataclass
class Sheet:
    index: int  # 0-based page index
    width: float
    height: float
    runs: list[TextRun] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    circles: list[Circle] = field(default_factory=list)
    rects: list[tuple[float, float, float, float]] = field(default_factory=list)
    image_path: str = ""  # rendered PNG
    image_scale: float = RENDER_DPI / 72  # pixels per PDF point
    titleblock_x: float | None = None  # scans only: left edge of the title-block box, from the raster
    ocr_tiles: int = 0  # scans: tiles the tiled OCR pass read this page in (0 = not tiled, -1 = count not reported)
    ocr_tile_scale: float = 0.0  # ... and the render scale (px per point) it used
    ocr_text_pt: float = 0.0  # ... chosen from this typical lettering height (pt) of the page's first pass
    ocr_vertical_tiles: int = 0  # tiles of the rotated pass for vertical text (0 = not run)

    @property
    def full_text(self) -> str:
        return "\n".join(r.text for r in self.runs)


@dataclass
class Document:
    doc_id: str
    source: str
    sheets: list[Sheet]
    is_vector: bool
    ocr_version: int = 0  # ocr.config.OCR_VERSION the cached text was read with (0 = OCR not available then)
    tile_version: int = 0  # ocr.config.TILE_VERSION the scans' tiled pass was run with (0 = not run)
    vocr_version: int = 0  # ocr.config.VOCR_VERSION the scans' vertical-text pass was run with (0 = not run)
    seg_version: int = 0  # ocr.config.SEG_VERSION the scans' raster lines were found with (0 = not found)
    from_ocr: bool = False  # True when the text runs came from OCR of a scan
