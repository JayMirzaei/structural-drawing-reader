"""What is kept between runs for a scanned PDF: per-page OCR results and each run's confidence;
and the repair of drawing numbers across the sheets of a scanned set.

The OCR engine itself is replaced by a stub, so these tests run without it."""

from __future__ import annotations

import pymupdf

from drawing_reader import ocr
from drawing_reader.ingest import Document, ingest, load_cached
from drawing_reader.ingest.cache import load_document, write_document
from drawing_reader.ocr.runs import repair_drawing_numbers
from support import make_run, make_sheet


def test_run_confidence_survives_the_cache_round_trip(tmp_path):
    """A run's OCR confidence and the document's "read by OCR" flag come back from the cache file."""
    run = make_run("C", 2, 2, 5.0, x1=6, y1=8, conf=0.7)
    doc = Document(
        doc_id="test",
        source="made_up.pdf",
        sheets=[make_sheet([run], width=20, height=20)],
        is_vector=False,
        from_ocr=True,
    )
    write_document(tmp_path, doc)
    back = load_document(tmp_path)
    assert back.from_ocr
    assert back.sheets[0].runs[0].conf == 0.7


def test_ocr_result_is_kept_per_page_and_not_repeated(tmp_path, monkeypatch):
    """When the primitives file is gone the PDF is extracted again, but each page's OCR result is
    reused, even an empty one: the engine runs once per page."""
    pdf = tmp_path / "blank.pdf"
    blank = pymupdf.open()
    blank.new_page()
    blank.save(pdf)
    blank.close()
    pages_read = []
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "is_scanned_page", lambda page: True)
    monkeypatch.setattr(ocr, "titleblock_left_x", lambda page: None)
    monkeypatch.setattr(ocr, "ocr_page", lambda page, i, run_cls: pages_read.append(i) or [])
    monkeypatch.setattr(ocr, "raster_segments", lambda page, seg_cls: [])  # the engine extra may be absent
    cache = tmp_path / "cache"
    ingest(pdf, cache)
    for primitives in cache.glob("*/primitives.json"):
        primitives.rename(primitives.with_suffix(".gone"))
    doc = ingest(pdf, cache)
    assert pages_read == [0]
    assert doc.from_ocr
    assert load_cached(pdf, cache).from_ocr


# --- drawing numbers of a scanned set -------------------------------------------------------------


def _numbered(*texts):
    """One sheet per text, each holding that text as its drawing number."""
    return [make_sheet([make_run(t, 80, 90, 5.0, x1=90, y1=95, conf=0.9)], width=100, height=100) for t in texts]


def _numbers(sheets):
    return [sheet.runs[0].text for sheet in sheets]


def test_dropped_suffix_is_restored_when_the_whole_set_uses_one_letter():
    """Every other sheet reads "<digits>-B", so a number cut at its dash gets the B back."""
    sheets = _numbered("41200-B", "41201-B", "41203-B", "41202-")
    repair_drawing_numbers(sheets)
    assert _numbers(sheets)[3] == "41202-B"


def test_misread_or_missing_dash_is_restored_only_for_the_sets_own_letter():
    """ "=" for the dash and a dash left out are repaired; a number with a letter the set does not
    use is left as read."""
    sheets = _numbered("41200-B", "41201-B", "41203-B", "41204=B", "41205B", "63045S")
    repair_drawing_numbers(sheets)
    assert _numbers(sheets)[3:] == ["41204-B", "41205-B", "63045S"]


def test_dropped_suffix_is_left_alone_when_the_set_mixes_letters():
    """With two suffix letters in use there is no single letter to restore, so nothing is guessed."""
    sheets = _numbered("41200-B", "41201-S", "41203-B", "41205-S", "41202-")
    repair_drawing_numbers(sheets)
    assert _numbers(sheets)[4] == "41202-"
