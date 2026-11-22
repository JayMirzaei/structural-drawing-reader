"""Pages stored rotated.

A PDF page can be stored on its side with a `/Rotate` entry telling the viewer to turn it. The PDF
library reports text and line coordinates in the stored (unrotated) frame, while the page size and
the rendered image are in the displayed frame. Ingestion moves every primitive into the displayed
frame, so the rules see a rotated page exactly as a reader sees it.
"""

from __future__ import annotations

import pymupdf
import pytest

from drawing_reader.ingest import ingest
from drawing_reader.parse import build_index
from support import EXAMPLE_SET

ROTATED_PAGE = 3  # 0-based: S-301 in the example set


def rotated_pdf(path, rotation):
    """One tabloid page stored on its side and displayed landscape (1224 x 792) through `rotation`,
    with a sheet number and a title lettered so that they read horizontally once the page is turned."""
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=1224)
    page.set_rotation(rotation)
    to_stored = ~page.rotation_matrix  # displayed frame -> stored frame
    for text, at, size in (("S2-03", (980, 720), 24), ("MEZZANINE PLAN", (980, 750), 18)):
        page.insert_text(pymupdf.Point(at) * to_stored, text, fontsize=size, rotate=rotation)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_rotated_page_gives_its_sheet_number_and_title(tmp_path, rotation):
    """Without the move into the displayed frame the title block lies outside the page, and the
    sheet falls back to its page number."""
    idx = build_index(ingest(rotated_pdf(tmp_path / "rotated.pdf", rotation), tmp_path / "cache"))
    (sheet,) = idx.sheets
    assert (sheet.width, sheet.height) == (1224, 792)
    assert sheet.number == "S2-03"
    assert sheet.title == "MEZZANINE PLAN"


@pytest.mark.parametrize("rotation", [90, 270])
def test_text_of_a_rotated_page_lies_inside_the_displayed_page_and_reads_horizontally(tmp_path, rotation):
    doc = ingest(rotated_pdf(tmp_path / "rotated.pdf", rotation), tmp_path / "cache")
    (sheet,) = doc.sheets
    assert sorted(r.text for r in sheet.runs) == ["MEZZANINE PLAN", "S2-03"]
    for r in sheet.runs:
        x0, y0, x1, y1 = r.bbox
        assert 0 <= x0 < x1 <= sheet.width and 0 <= y0 < y1 <= sheet.height
        assert r.dir == pytest.approx((1.0, 0.0), abs=1e-6)
        assert x1 - x0 > y1 - y0  # a horizontal line of text is wider than tall


# --- the rotated sheet of the example set -----------------------------------------------------------


def test_the_example_set_stores_one_sheet_rotated():
    """S-301 is stored portrait with a quarter turn; the other sheets are stored as displayed."""
    with pymupdf.open(EXAMPLE_SET) as pdf:
        assert [page.rotation for page in pdf] == [0, 0, 0, 90, 0]
        stored = pdf[ROTATED_PAGE].mediabox
        assert (stored.width, stored.height) == (792, 1224)


def test_the_rotated_sheet_is_displayed_like_the_others(platform, platform_doc):
    assert {(s.width, s.height) for s in platform.sheets} == {(1224, 792)}
    assert {(s.width, s.height) for s in platform_doc.sheets} == {(1224, 792)}


def test_the_rotated_sheet_title_block_reads_like_the_others(platform):
    rotated, plain = platform.sheets[ROTATED_PAGE], platform.sheets[1]
    assert (rotated.number, rotated.title, rotated.scale) == ("S-301", "TYPICAL DETAILS", "1:10")
    assert set(rotated.fields) == set(plain.fields)
    assert rotated.fields["Client"] == plain.fields["Client"]
    assert rotated.fields["Project No"] == plain.fields["Project No"]


def test_shared_title_block_fields_sit_at_the_same_place_on_the_rotated_sheet(platform):
    """The title block is drawn identically on every sheet, so a field's box on the rotated sheet
    matches its box on an unrotated one."""

    def field_box(sheet, name):
        return next(f.bbox for f in platform.by_kind("titleblock") if f.sheet == sheet and f.attrs["field"] == name)

    for name in ("Client", "Project No", "Checked By"):
        assert field_box("S-301", name) == pytest.approx(field_box("S-101", name), abs=1.0)


def test_every_fact_of_the_rotated_sheet_lies_inside_the_page(platform):
    facts = [f for f in platform.facts if f.sheet == "S-301"]
    assert len(facts) > 50
    for f in facts:
        x0, y0, x1, y1 = f.bbox
        assert 0 <= x0 <= x1 <= 1224 and 0 <= y0 <= y1 <= 792, f.id


def test_geometry_rules_work_on_the_rotated_sheet(platform):
    """Rules that pair text with lines (dimension strings, revision rows, views) need both in one
    frame: the base plate's 50 + 250 + 50 string adds up to its 350 overall on the rotated sheet."""
    dims = [f for f in platform.by_kind("dimension") if f.sheet == "S-301" and f.view == "COLUMN BASE PLATE"]
    horizontal = [f for f in dims if f.attrs.get("orientation") == "horizontal" and f.attrs.get("dim_kind") == "linear"]
    assert sorted(f.value for f in horizontal if f.attrs.get("chain_ok")) == ["250", "50", "50"]
    assert [f.value for f in horizontal if f.attrs.get("chain_total")] == ["350"]
    revisions = [f.attrs["number"] for f in platform.by_kind("revision") if f.sheet == "S-301"]
    assert revisions == ["A", "B", "0", "1"]
    views = {f.value for f in platform.by_kind("view") if f.sheet == "S-301"}
    assert "COLUMN BASE PLATE" in views and len(views) == 3
