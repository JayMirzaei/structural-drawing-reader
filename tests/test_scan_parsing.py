"""How the parser treats text that came from OCR, tested on hand-built OCR-shaped runs (confidence
below 1.0, padded boxes, misreads). No OCR engine is needed: nothing here reads an image."""

from __future__ import annotations

import pytest

from drawing_reader.ingest import Document
from drawing_reader.ocr.config import OCR_CONF_CAP
from drawing_reader.ocr.engine import _RE_RATIO_MISREAD
from drawing_reader.ocr.runs import group_blocks
from drawing_reader.parse.index import _common_large_texts
from drawing_reader.qa import OCR_ANSWER_CAP, answer
from support import index_sheets, make_run, make_sheet

WIDTH, HEIGHT = 3000, 1800  # a scan's page in points is large: its text boxes are 24-30 pt high


def _scan_run(n, text, x, y, size=24.0, conf=0.95):
    return make_run(text, x, y, size, x1=x + 9 * len(text), y1=y + size, conf=conf, block=n, run_id=f"p1.t{n:03d}")


def _scan_index(runs, **sheet_extra):
    return index_sheets(make_sheet(runs, width=WIDTH, height=HEIGHT, **sheet_extra), from_ocr=True)


# --- confidence -----------------------------------------------------------------------------------


def test_facts_from_a_scan_are_capped_and_flagged():
    """OCR text is approximate: every fact built from it is marked and never exceeds the OCR cap."""
    idx = _scan_index(
        [
            _scan_run(1, "GENERAL NOTES", 200, 200, 30.0),
            _scan_run(2, "1. GROUT f'c = 40 MPa", 200, 260),
            _scan_run(3, "2. PLATE Fy = 300 MPa", 200, 310),
        ]
    )
    assert idx.facts
    assert all(f.confidence <= OCR_CONF_CAP and f.attrs.get("ocr") for f in idx.facts)


def test_answer_from_a_scan_is_capped_and_says_it_was_read_by_ocr():
    """An answer that cites OCR-read facts carries an OCR caveat and a capped confidence."""
    idx = _scan_index(
        [_scan_run(1, "GENERAL NOTES", 200, 200, 30.0), _scan_run(2, "1. CONCRETE f'c = 35 MPa", 200, 260)]
    )
    a = answer("What is the concrete strength?", idx, llm=None)
    assert a.fact_ids
    assert a.confidence <= OCR_ANSWER_CAP
    assert any("OCR" in caveat for caveat in a.caveats)


# --- title block of a scan ------------------------------------------------------------------------


def test_numeric_drawing_number_cut_at_its_dash_is_the_sheet_number_on_a_scan():
    """Older sets number drawings "12345-X"; when the scan loses the suffix ("41207-") the digits
    still name the sheet, ahead of other numbers in the title block."""
    idx = _scan_index(
        [
            _scan_run(1, "R274", 2300, 1680, 26.0),
            _scan_run(2, "64318-S", 2384, 1682, 26.0),
            _scan_run(3, "41207-", 2520, 1680, 26.0),
            _scan_run(4, "GENERAL NOTES", 200, 200, 14.0),
        ]
    )
    assert idx.sheets[0].number == "41207"


def _view_beside_the_title_block(**sheet_extra):
    runs = [
        _scan_run(1, "ELEVATION", 150, 1580, 26.0),
        _scan_run(2, "1:7.5", 170, 1606, 17.0),
        _scan_run(3, "41209-B", 2500, 1680, 26.0),
    ]
    return [f for f in _scan_index(runs, **sheet_extra).facts if f.kind == "view"]


def test_text_left_of_the_scanned_title_block_box_stays_in_the_drawing():
    """With the title-block box found in the raster, a view title and scale low on the sheet but
    left of the box are drawing text: the view is read with its scale."""
    views = _view_beside_the_title_block(titleblock_x=1250.0)
    assert [(v.value, v.attrs.get("scale")) for v in views] == [("ELEVATION", "1:7.5")]


def test_without_a_title_block_box_the_bottom_band_is_all_title_block():
    """The same sheet with no box edge: the bottom band is title block, so no view is read there."""
    assert _view_beside_the_title_block() == []


def test_repeated_logo_read_differently_on_each_page_is_common_text():
    """OCR reads one printed logo three ways on three sheets; near-identical spellings count as the
    same repeated text (not a sheet title), while titles that differ in a digit stay distinct."""
    logos = ["orvaleERECTORS", "orvaIeERECTORS", "NorvaIe ERECTORS"]
    sheets = [
        make_sheet(
            [
                make_run(logo, 2300, 1540, 30.0, x1=2600, y1=1570, conf=0.9, block=1),
                make_run(f"STAIR - SHEET {n}", 2300, 1640, 30.0, x1=2600, y1=1670, conf=0.9, block=2),
            ],
            width=WIDTH,
            height=HEIGHT,
        )
        for n, logo in enumerate(logos)
    ]
    doc = Document(doc_id="test", source="made_up.pdf", sheets=sheets, is_vector=False, from_ocr=True)
    common = _common_large_texts(doc)
    assert set(logos) <= common
    assert "STAIR - SHEET 1" not in common


def test_scan_title_joins_the_runs_of_one_row_and_skips_the_logo():
    """A title that OCR split into two boxes on one row is joined; the logo above it and a stray
    word elsewhere are not part of it."""
    idx = _scan_index(
        [
            _scan_run(1, "orvaleERECTORS", 2319, 1521, 31.0),
            _scan_run(2, "Vexta", 1259, 1545, 34.0),
            _scan_run(3, "TRUSSES -", 2334, 1629, 26.0),
            _scan_run(4, "SHEET 2", 2439, 1629, 26.0),
            _scan_run(5, "41210-B", 2523, 1670, 26.0),
        ]
    )
    assert idx.sheets[0].title == "TRUSSES - SHEET 2"


# --- notes on a scan ------------------------------------------------------------------------------


def test_wrapped_note_lines_share_a_block_and_the_next_item_starts_a_new_one():
    """OCR gives one box per line: lines at a tight pitch are one paragraph, a wider gap starts the
    next item."""
    runs = [
        _scan_run(1, "ALL BOLTS SHALL CONFORM TO", 150, 150),
        _scan_run(2, "ASTM A325M TYPE 1.", 150, 167),
        _scan_run(3, "ALL WELDS SHALL BE CONTINUOUS", 150, 191),
    ]
    group_blocks(runs)
    assert runs[0].block == runs[1].block
    assert runs[2].block != runs[0].block


def _class_notes_index():
    runs = [
        _scan_run(1, "GENERAL NOTES", 2160, 200, 30.0),
        _scan_run(2, "DECK CONCRETE SHALL BE CLASS C AND", 2050, 260),
        _scan_run(3, "BARRIER CONCRETE SHALL BE CLASS HPC.", 2050, 277),
        _scan_run(4, "ALL STEEL SHALL CONFORM TO CSA G40.21M350W", 2050, 320),
    ]
    group_blocks(runs)
    return _scan_index(runs)


def test_unnumbered_notes_under_a_scanned_general_notes_heading_are_listed():
    """On a scan the notes under a GENERAL NOTES heading are found without item numbers, and a
    wrapped note is listed as one sentence."""
    a = answer("What are the general notes?", _class_notes_index())
    assert a.method == "rule:general-notes"
    assert "CLASS C AND BARRIER CONCRETE SHALL BE CLASS HPC" in a.text
    assert "CSA G40.21M350W" in a.text


def test_concrete_specified_by_class_is_reported_as_a_class_not_a_strength():
    """Bridge and civil notes give a concrete class instead of MPa: the answer says so and quotes it."""
    a = answer("What is the concrete strength?", _class_notes_index())
    assert a.method == "rule:concrete"
    assert "class" in a.text and "CLASS HPC" in a.text
    assert any("not an MPa value" in caveat for caveat in a.caveats)


def test_concrete_strength_stated_in_a_sentence_is_reported():
    """ "... MINIMUM f'c OF 35 MPa ..." in prose answers the concrete strength question directly."""
    idx = _scan_index([_scan_run(1, "CONCRETE SHALL HAVE A MINIMUM f'c OF 35 MPa AT 28 DAYS.", 150, 150)])
    a = answer("What is the concrete strength?", idx)
    assert a.method == "rule:concrete"
    assert "35 MPa" in a.text


# --- misread ratio --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "restored"),
    [("1; 7.5", "1:7.5"), ("1|40", "1:40"), ("1!20", "1:20"), ("320.5", "320.5"), ("PL 1; 4", "PL 1; 4")],
)
def test_colon_of_a_scale_ratio_misread_by_ocr_is_restored(read, restored):
    """A ratio's colon read as ";", "|" or "!" is put back when the whole run is the ratio; a
    decimal number and a ratio inside other text are left alone."""
    assert _RE_RATIO_MISREAD.sub(r"\1:\2", read) == restored
