"""The OCR path of ingestion: geometry helpers for recognised boxes, and when a page with some text
layer is still read from its pixels. The engine is replaced by a stand-in, so nothing here needs the
OCR extra installed."""

from __future__ import annotations

import math

import pymupdf
import pytest

from drawing_reader import ocr
from drawing_reader.ingest import TextRun, ingest, load_cached
from drawing_reader.ocr.engine import _dir_of, _keep_angle
from drawing_reader.ocr.runs import fix_vertical, iou
from support import make_run

NOTE_LINE = "ALL STRUCTURAL STEEL TO BE SHOP PRIMED UNLESS NOTED"


def write_pdf(path, lines):
    """A one-page PDF (A4, portrait) with the given (x, y, text) lines as its text layer."""
    doc = pymupdf.open()
    page = doc.new_page()
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=8)
    doc.save(str(path))
    doc.close()
    return path


def recognised(count, text="GIRT"):
    """What the stand-in engine "reads": `count` confident runs along the top of the page."""
    return [
        TextRun(
            id=f"p1.t{i:03d}",
            text=text,
            bbox=(12 + 8 * i, 14, 40 + 8 * i, 24),
            dir=(1.0, 0.0),
            size=10.0,
            block=i,
            conf=0.95,
        )
        for i in range(count)
    ]


@pytest.fixture
def engine(monkeypatch):
    """Replace the OCR engine: every page counts as a scan, and reading one returns `engine.runs`.
    `engine.pages` records the pages that were read."""

    class Engine:
        runs: list = []
        pages: list = []

    state = Engine()
    state.runs, state.pages = recognised(3), []

    def read_page(page, index, run_cls):
        state.pages.append(index)
        return list(state.runs)

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "is_scanned_page", lambda page: True)
    monkeypatch.setattr(ocr, "titleblock_left_x", lambda page: None)
    monkeypatch.setattr(ocr, "raster_segments", lambda page, seg_cls: [])
    monkeypatch.setattr(ocr, "ocr_page", read_page)
    return state


# --- boxes ------------------------------------------------------------------------------------------


def test_a_tall_narrow_box_is_text_running_up_the_page():
    """The detector's box is axis-aligned: a box much taller than wide with several characters is a
    vertical dimension or label, so it gets the upward direction and the short side as its size."""
    tall = make_run("3150", 110, 210, 32.0, x1=124, y1=242, conf=0.9)
    wide = make_run("3150", 110, 210, 14.0, x1=150, y1=224, conf=0.9)
    digit = make_run("7", 110, 210, 32.0, x1=124, y1=242, conf=0.9)
    fix_vertical([tall, wide, digit])
    assert tall.dir == (0.0, -1.0) and tall.size == 14.0
    assert wide.dir == (1.0, 0.0) and digit.dir == (1.0, 0.0)


def test_fixing_vertical_boxes_twice_changes_nothing_more():
    """Cached results are passed through the fix again on every load."""
    tall = make_run("3150", 110, 210, 32.0, x1=124, y1=242, conf=0.9)
    fix_vertical([tall])
    fix_vertical([tall])
    assert tall.dir == (0.0, -1.0) and tall.size == 14.0


def test_overlap_of_two_boxes():
    assert iou((0, 0, 20, 10), (0, 0, 20, 10)) == 1.0
    assert iou((0, 0, 20, 10), (40, 30, 60, 40)) == 0.0
    assert iou((0, 0, 20, 10), (10, 0, 30, 10)) == pytest.approx(1 / 3)


def test_text_at_an_angle_is_kept_only_when_the_engine_is_confident():
    """Upright text is always kept; a diagonal member's label only at high confidence, because a wrong
    rotation reads as garbage; near-vertical boxes are left to the vertical pass."""
    assert _keep_angle(math.radians(6), 0.55)
    assert not _keep_angle(math.radians(40), 0.8)
    assert _keep_angle(math.radians(-40), 0.95)
    assert not _keep_angle(math.radians(87), 0.99)


def test_reading_direction_of_a_box_at_an_angle():
    """Nearly upright text is exactly horizontal; a diagonal box reads along its own angle."""
    assert _dir_of(math.radians(9)) == (1.0, 0.0)
    dx, dy = _dir_of(math.radians(-30))
    assert (round(dx, 2), round(dy, 2)) == (0.87, -0.5)


# --- which pages are read from pixels -------------------------------------------------------------------


def test_a_page_with_no_text_layer_is_read_by_the_engine(engine, tmp_path):
    doc = ingest(write_pdf(tmp_path / "scan.pdf", []), tmp_path / "cache")
    assert doc.from_ocr and engine.pages == [0]
    assert [r.text for r in doc.sheets[0].runs] == ["GIRT"] * 3


def test_a_thin_markup_layer_over_a_scan_still_gets_ocr_and_keeps_its_own_text(engine, tmp_path):
    """A scan with a reviewer's typed markup has a short text layer: the page is read from pixels as
    well, and the markup's exact text is kept beside what was recognised."""
    lines = [(60, 300 + 14 * i, NOTE_LINE) for i in range(3)]
    doc = ingest(write_pdf(tmp_path / "markup.pdf", lines), tmp_path / "cache")
    texts = [r.text for r in doc.sheets[0].runs]
    assert doc.from_ocr and engine.pages == [0]
    assert texts.count("GIRT") == 3 and texts.count(NOTE_LINE) == 3
    assert ocr.config.TRIVIAL_TEXT_CHARS <= 3 * len(NOTE_LINE) < ocr.config.THIN_LAYER_CHARS


def test_a_full_text_layer_with_a_lettered_title_block_corner_is_not_read_again(engine, tmp_path):
    """A page with a real text layer, title block included, is left to the vector reader."""
    lines = [(60, 100 + 14 * i, NOTE_LINE) for i in range(10)]
    lines += [(420, 740 + 14 * i, "HARLOW CREEK DEPOT") for i in range(ocr.config.CORNER_MIN_RUNS)]
    doc = ingest(write_pdf(tmp_path / "vector.pdf", lines), tmp_path / "cache")
    assert not doc.from_ocr and engine.pages == []
    assert NOTE_LINE in [r.text for r in doc.sheets[0].runs]


def test_a_text_layer_missing_its_title_block_corner_is_read_from_pixels_too(engine, tmp_path):
    """A hidden text layer can miss the title block: fewer runs in the corner than the floor of the
    corner bar means the page is read by the engine as well, however long its layer is."""
    lines = [(60, 100 + 14 * i, NOTE_LINE) for i in range(10)]
    lines += [(420, 740 + 14 * i, "HARLOW CREEK DEPOT") for i in range(ocr.config.CORNER_MIN_RUNS - 1)]
    doc = ingest(write_pdf(tmp_path / "no_corner.pdf", lines), tmp_path / "cache")
    assert doc.from_ocr and engine.pages == [0]


# --- the tiled pass --------------------------------------------------------------------------------


def test_tiling_details_are_recorded_per_page_and_survive_the_cache(engine, tmp_path, monkeypatch):
    """A page with many runs is read again tile by tile; how it was tiled (tile count, scale, the
    lettering height the scale was chosen from) is kept on the sheet and in the cache."""
    engine.runs = recognised(70)
    seen = {}

    def tiled(page, index, run_cls, text_pt=None):
        seen["text_pt"] = text_pt
        return [], {"tiles": 4, "grid": 6, "scale": 2.3, "text_pt": text_pt or 0.0}

    monkeypatch.setattr(ocr, "ocr_tiled", tiled)
    pdf = write_pdf(tmp_path / "scan.pdf", [])
    sheet = ingest(pdf, tmp_path / "cache").sheets[0]
    assert (sheet.ocr_tiles, sheet.ocr_tile_scale, sheet.ocr_vertical_tiles) == (4, 2.3, 0)
    assert sheet.ocr_text_pt == seen["text_pt"] == 7.0  # 0.7 x the 10 pt boxes of the first pass
    again = load_cached(pdf, tmp_path / "cache").sheets[0]
    assert (again.ocr_tiles, again.ocr_tile_scale, again.ocr_text_pt) == (4, 2.3, 7.0)


def test_a_page_with_few_runs_is_not_tiled(engine, tmp_path, monkeypatch):
    """Only a dimensioned drawing (many runs, or many bare numbers) pays for the second pass."""

    def tiled(*args, **kwargs):
        raise AssertionError("the tiled pass must not run")

    monkeypatch.setattr(ocr, "ocr_tiled", tiled)
    sheet = ingest(write_pdf(tmp_path / "scan.pdf", []), tmp_path / "cache").sheets[0]
    assert sheet.ocr_tiles == 0
