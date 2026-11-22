"""Where the title block ends and the drawing area begins: a strip along the bottom of the sheet,
or a strip down its right-hand side behind a tall vertical divider."""

from __future__ import annotations

from drawing_reader.parse.layout import bottom_band_y
from drawing_reader.parse.sheet.parser import SheetParser
from support import make_run, make_sheet, segment

WIDTH, HEIGHT = 1224, 792
DIVIDER = segment(1040, 60, 1040, 720, width=1.0)  # tall line near the right edge


def strip_runs() -> dict:
    """Title-block text right of the divider: three cells above the bottom band, two inside it."""
    return {
        "consultant": make_run("STRUCTURAL CONSULTANT", 1060, 120, 8, block=1),
        "project_no": make_run("PROJECT NO: PN-4172", 1060, 220, 8, block=1),
        "drawn_by": make_run("DRAWN BY: QEV", 1060, 320, 8, block=1),
        "sheet_no": make_run("S-101", 1060, 690, 14, block=1),
        "scale_label": make_run("SCALE", 1060, 740, 8, block=1),
    }


def view_title_runs() -> dict:
    """A view title and its scale note, low on the sheet: inside the bottom band, left of the strip."""
    return {
        "title": make_run("GROUND FLOOR FRAMING PLAN", 150, 664, 10),
        "scale": make_run("SCALE:  1 : 50", 150, 680, 9),
    }


def test_right_hand_strip_keeps_low_drawing_text_in_the_drawing_area():
    """With a right-hand title strip, a view title near the bottom of the sheet is drawing-area
    text. A plain bottom-band split would file it in the title block, where no body rule sees it."""
    strip, low = strip_runs(), view_title_runs()
    parser = SheetParser(make_sheet([*low.values(), *strip.values()], [DIVIDER], width=WIDTH, height=HEIGHT))
    assert low["title"] in parser.body and low["scale"] in parser.body
    assert strip["sheet_no"] in parser.tb

    parser.parse_grids_callouts_elevations()
    views = [f for f in parser.facts if f.kind == "view"]
    assert len(views) == 1
    assert views[0].attrs["title"] == "GROUND FLOOR FRAMING PLAN"
    assert views[0].attrs["scale"] == "1 : 50"


def test_without_a_divider_the_bottom_band_is_the_title_block():
    """The same text with no divider line: the split is the plain bottom band, so sheets with a
    bottom title strip are read as before."""
    runs = [*view_title_runs().values(), *strip_runs().values()]
    sheet = make_sheet(runs, width=WIDTH, height=HEIGHT)
    parser = SheetParser(sheet)
    band = bottom_band_y(sheet)
    assert {r.id for r in parser.tb} == {r.id for r in runs if r.bbox[1] >= band}
    assert {r.id for r in parser.body} == {r.id for r in runs if r.bbox[1] < band}
    assert len(parser.tb) == 4 and len(parser.body) == 3


def test_revision_rows_left_of_the_divider_are_still_revisions():
    """A revision log in the bottom band but left of a right-hand strip is drawing-area text by
    position. Its numbered rows are still revisions, not notes or loose text."""
    strip = strip_runs()
    rows = [
        make_run("0", 480, 662, 8, block=2, run_id="p1.r0"),
        make_run("ISSUED FOR TENDER", 500, 662, 8, block=2),
        make_run("MAR 9, 2031", 640, 662, 8, block=2),
        make_run("1", 480, 682, 8, block=2, run_id="p1.r1"),
        make_run("ISSUED FOR CONSTRUCTION", 500, 682, 8, block=2),
        make_run("JUN 3, 2031", 640, 682, 8, block=2),
    ]
    parser = SheetParser(make_sheet([*strip.values(), *rows], [DIVIDER], width=WIDTH, height=HEIGHT))
    assert rows[0] in parser.body and rows[3] in parser.body

    parser.parse_titleblock(set())
    parser.parse_notes()
    parser.parse_remaining_text()

    revisions = {f.attrs["number"]: f for f in parser.facts if f.kind == "revision"}
    assert set(revisions) == {"0", "1"}
    assert revisions["0"].attrs["description"] == "ISSUED FOR TENDER"
    assert revisions["1"].attrs["description"] == "ISSUED FOR CONSTRUCTION"
    assert all("ISSUED FOR" not in f.source_text for f in parser.facts if f.kind in ("note", "text"))
