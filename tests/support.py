"""Helpers for building invented test data: facts, text runs, sheets, and small drawn PDFs."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pymupdf

from drafting import Canvas, new_sheet
from drawing_reader.ingest import Circle, Document, Segment, Sheet, TextRun, ingest
from drawing_reader.parse import build_index
from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.schema import Fact, Index, SheetMeta

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXAMPLE_SET = EXAMPLES / "access_platform_set.pdf"
EXAMPLE_SCAN = EXAMPLES / "access_platform_scan.pdf"


def make_fact(fid: str, kind: str, value: str, sheet: str, **attrs) -> Fact:
    return Fact(
        id=fid, kind=kind, value=value, sheet=sheet, page=1, bbox=(10, 10, 60, 20), source_text=value, attrs=attrs
    )


def make_index(*facts: Fact, sheets: Iterable[str | SheetMeta] = ("S-101",), **fields) -> Index:
    """A hand-built index: the given facts on sheets with the given numbers (or full `SheetMeta`s)."""
    metas = [s if isinstance(s, SheetMeta) else SheetMeta(page=i, number=s) for i, s in enumerate(sheets, 1)]
    return Index(doc_id="test", source="made_up.pdf", is_vector=True, sheets=metas, facts=list(facts), **fields)


def reply(
    answer: str = "The base plate is 38mm thick.", cited: list[str] | None = None, confidence: float = 0.9
) -> dict:
    """A model reply in the LLMAnswer shape."""
    return {
        "answer": answer,
        "cited_fact_ids": ["S-501.note.001"] if cited is None else cited,
        "sheets_used": ["S-501"],
        "confidence": confidence,
        "caveats": [],
    }


def make_run(
    text: str,
    x: float,
    y: float,
    size: float = 8.0,
    *,
    x1: float | None = None,
    y1: float | None = None,
    direction: tuple[float, float] = (1.0, 0.0),
    conf: float = 1.0,
    block: int = 0,
    run_id: str | None = None,
) -> TextRun:
    """A text run whose top-left corner is (`x`, `y`). Without `x1`/`y1` the box is sized the way
    PyMuPDF sizes Helvetica: about half the font size per character wide, 1.37 font sizes high. A
    vertical run (direction (0, -1)) gets the same box turned on its side."""
    length, height = 0.55 * size * len(text), 1.37 * size
    if abs(direction[1]) > abs(direction[0]):
        length, height = height, length
    box = (x, y, x + length if x1 is None else x1, y + height if y1 is None else y1)
    return TextRun(
        id=run_id or f"p1.t{abs(hash((text, x, y))) % 10**6:06d}",
        text=text,
        bbox=box,
        dir=direction,
        size=size,
        block=block,
        conf=conf,
    )


def make_sheet(
    runs: Iterable[TextRun],
    segments: Iterable[Segment] = (),
    circles: Iterable[Circle] = (),
    width: float = 1224,
    height: float = 792,
    **extra,
) -> Sheet:
    return Sheet(
        index=0, width=width, height=height, runs=list(runs), segments=list(segments), circles=list(circles), **extra
    )


def segment(x0: float, y0: float, x1: float, y1: float, width: float = 0.35, dashed: bool = False) -> Segment:
    return Segment((x0, y0), (x1, y1), width, dashed)


def circle(cx: float, cy: float, radius: float, width: float = 0.35, arcs: int = 4) -> Circle:
    return Circle((cx - radius, cy - radius, cx + radius, cy + radius), arcs, width)


def parse_sheet(sheet: Sheet, common_large_texts: Iterable[str] = ()) -> tuple[SheetMeta, list[Fact]]:
    """Run the per-sheet parser on one hand-built sheet."""
    return SheetParser(sheet).run(set(common_large_texts))


def index_sheets(*sheets: Sheet, from_ocr: bool = False) -> Index:
    """Build the index of a hand-built document (pages are renumbered in the order given)."""
    for i, sheet in enumerate(sheets):
        sheet.index = i
    doc = Document(doc_id="test", source="made_up.pdf", sheets=list(sheets), is_vector=not from_ocr, from_ocr=from_ocr)
    return build_index(doc)


def draw_pdf(path: Path, *pages: Callable[[Canvas], None], size: tuple[float, float] = (1224, 792)) -> Path:
    """Write a PDF with one sheet per drawing function (each gets a `drafting.Canvas`)."""
    doc = pymupdf.open()
    for draw in pages:
        draw(new_sheet(doc, *size))
    doc.save(str(path))
    return path


def draw_index(tmp_path: Path, *pages: Callable[[Canvas], None], size: tuple[float, float] = (1224, 792)) -> Index:
    """Draw the pages, then read them back through the whole pipeline (ingest and parse)."""
    pdf = draw_pdf(tmp_path / "drawn.pdf", *pages, size=size)
    return build_index(ingest(pdf, tmp_path / "cache"))
