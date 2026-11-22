"""Small deterministic pieces touched while restructuring the package."""

from __future__ import annotations

import pytest

from drawing_reader import ocr
from drawing_reader.parse.members import _mixed_number, parse_extended_member
from drawing_reader.qa import first_look
from drawing_reader.regression import diff_snapshots, snapshot_path
from drawing_reader.schema import Index


@pytest.mark.parametrize(
    ("text", "value"), [("12.7", 12.7), ("3/8", 0.375), ("3-1/2", 3.5), ("08", 8.0), ("0/4", 0.0), ("1-1/16", 1.0625)]
)
def test_mixed_number_values(text, value):
    assert _mixed_number(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["01/2", "1/02", "a/2", "1/2/3", ""])
def test_mixed_number_rejects_what_is_not_a_size(text):
    with pytest.raises(ValueError):
        _mixed_number(text)


def test_mixed_number_zero_denominator():
    with pytest.raises(ZeroDivisionError):
        _mixed_number("1/0")


def test_imperial_plate_thickness_is_the_smallest_dimension():
    family, section, attrs = parse_extended_member("PL 3/8 x 6 x 10")
    assert family == "PL" and section == "PL3/8X6X10"
    assert attrs["thickness"] == "3/8" and attrs["plan"] == "6X10" and attrs["units"] == "imperial"
    assert parse_extended_member("PL 1/0 x 6") is None  # not a size: left for other rules


def test_first_look_says_how_the_text_was_read(idx, monkeypatch):
    """Whether OCR would help a low-text PDF depends on whether it is installed, not on the run count alone."""
    assert "vector PDF" in first_look(idx)
    scan = Index(doc_id="d", source="scan.pdf", is_vector=False, from_ocr=True)
    assert "read by OCR" in first_look(scan)
    low_text = Index(doc_id="d", source="scan.pdf", is_vector=False)
    monkeypatch.setattr(ocr, "available", lambda: False)
    assert "OCR is not installed" in first_look(low_text)
    monkeypatch.setattr(ocr, "available", lambda: True)
    assert "OCR is not installed" not in first_look(low_text) and "little or no text" in first_look(low_text)


def test_snapshot_diff_reports_only_what_changed(tmp_path):
    old = {"sheet_count": 5, "is_vector": True, "fact_counts": {"note": 10, "label": 4}, "probes": {"q": {"text": "a"}}}
    new = {"sheet_count": 5, "is_vector": True, "fact_counts": {"note": 11, "grid": 2}, "probes": {"q": {"text": "b"}}}
    assert diff_snapshots(old, old) == []
    diffs = diff_snapshots(old, new)
    assert "fact_counts[note]: 10 -> 11" in diffs and "fact_counts[label]: 4 -> 0" in diffs
    assert "fact_counts[grid]: 0 -> 2" in diffs and any(d.startswith("probe 'q'") for d in diffs)
    drawings = tmp_path / "drawings"
    path = snapshot_path(drawings / "job a" / "set 1.pdf", drawings, tmp_path / "snapshots")
    assert path == tmp_path / "snapshots" / "job_a_set_1_pdf.json"
