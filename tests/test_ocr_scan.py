"""The OCR path end to end, on the rasterised framing plan (needs the `ocr` extra; skipped without it)."""

from __future__ import annotations

from drawing_reader.ocr.config import OCR_CONF_CAP
from drawing_reader.qa import OCR_ANSWER_CAP, answer


def test_a_scan_is_read_by_ocr_and_says_so(platform_scan):
    assert platform_scan.from_ocr and not platform_scan.is_vector
    assert all(f.confidence <= OCR_CONF_CAP and f.attrs.get("ocr") for f in platform_scan.facts)


def test_the_title_block_of_the_scan(platform_scan):
    sheet = platform_scan.sheets[0]
    assert (sheet.number, sheet.title, sheet.scale) == ("S-101", "PLATFORM FRAMING PLAN", "1:50")


def test_member_labels_are_read_from_the_raster_with_their_direction(platform_scan):
    labels = platform_scan.by_kind("label")
    sections = {f.attrs["section"].upper() for f in labels}
    assert {"W310X39", "W250X33", "W200X27"} <= sections
    assert {f.attrs["orientation"] for f in labels if f.attrs["section"].upper() == "W250X33"} == {"vertical"}


def test_dimension_lines_are_found_in_the_raster(platform_scan):
    values = {f.value for f in platform_scan.by_kind("dimension")}
    assert {"5200", "1500"} <= values


def test_evidence_boxes_lie_on_the_page(platform_scan):
    sheet = platform_scan.sheets[0]
    for f in platform_scan.facts:
        x0, y0, x1, y1 = f.bbox
        assert -2 <= x0 <= x1 <= sheet.width + 2 and -2 <= y0 <= y1 <= sheet.height + 2


def test_an_answer_from_a_scan_is_capped_and_carries_a_caveat(platform_scan):
    a = answer("Where is W200X27 used?", platform_scan, llm=None)
    assert a.method == "rule:member-lookup" and a.confidence <= OCR_ANSWER_CAP
    assert any("OCR" in c for c in a.caveats)
