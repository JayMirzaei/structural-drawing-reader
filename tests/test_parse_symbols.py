"""Drafting symbols read from text and circles: view titles, the number bubble beside a view
title, grid bubbles, and a revision table laid out under column headers."""

from drawing_reader.ingest import Circle
from drawing_reader.parse.sheet.parser import SheetParser
from support import circle, make_run, make_sheet

OWN_SHEET = "S40-03"
VIEW_TITLE = "PIER CAP AT EXTERIOR STEEL POST"


def boxed(text, x0, y0, x1, y1, size=10.0):
    """A text run with an explicit box."""
    return make_run(text, x0, y0, size, x1=x1, y1=y1)


def symbols_of(runs, circles=(), own_sheet=None):
    """Run the symbol pass (and the view-number merge) on loose runs; return the facts by kind."""
    parser = SheetParser(make_sheet(runs, circles=circles, width=2448, height=1584))
    if own_sheet:
        parser.meta.number = own_sheet
    parser.parse_grids_callouts_elevations()
    parser.merge_view_number_markers()
    return {kind: [f for f in parser.facts if f.kind == kind] for kind in ("view", "callout", "grid")}


def view_with_number_bubble(title_x):
    """A view title with its scale below, and a bubble (number over the sheet's own number) whose
    right edge is at x = 146, on the same row as a title starting at `title_x`."""
    return [
        boxed("4", 100, 200, 110, 210),
        boxed(OWN_SHEET, 98, 212, 146, 222),
        boxed(VIEW_TITLE, title_x, 200, title_x + 240, 210),
        boxed("1 : 25", title_x, 215, title_x + 40, 225, size=9.9),
    ]


# ---- view titles --------------------------------------------------------------------------------
def test_view_title_found_when_the_scale_line_carries_a_label():
    """The scale under a view title may be a bare ratio or 'SCALE: 1 : N' in one run; both mark
    the line above as a view title."""
    found = symbols_of(
        [
            boxed("TYPICAL PIPE RACK SUPPORT FRAMING", 100, 200, 300, 212),
            boxed("SCALE:  1 : 25", 100, 215, 180, 225, size=9.9),
        ]
    )
    (view,) = found["view"]
    assert view.attrs["title"] == "TYPICAL PIPE RACK SUPPORT FRAMING"
    assert view.attrs["scale"] == "1 : 25"


# ---- view-number bubbles ------------------------------------------------------------------------
def test_bubble_beside_a_view_title_is_the_view_number_not_a_callout():
    """A callout-shaped bubble naming its own sheet, directly left of a view title on the same row,
    numbers that view: it is not a cross-reference from the sheet to itself."""
    found = symbols_of(view_with_number_bubble(title_x=160), own_sheet=OWN_SHEET)
    (view,) = found["view"]
    assert view.attrs["number"] == "4"
    assert view.source_text.startswith("4 ")
    assert view.bbox[0] <= 100
    assert found["callout"] == []


def test_bubble_is_dropped_when_the_title_already_took_its_number():
    """When the bubble sits close enough for its top half to be read with the title, the view has
    its number already; the bubble must still not survive as a callout to its own sheet."""
    found = symbols_of(view_with_number_bubble(title_x=140), own_sheet=OWN_SHEET)
    (view,) = found["view"]
    assert view.attrs["number"] == "4"
    assert found["callout"] == []


def test_bubble_far_from_the_view_title_stays_a_callout():
    """The same bubble well away from the title is an ordinary callout to a detail on the same
    sheet: nearness to a view title is the signal, not the self-reference alone."""
    found = symbols_of(view_with_number_bubble(title_x=230), own_sheet=OWN_SHEET)
    (view,) = found["view"]
    assert view.attrs["number"] == ""
    (callout,) = found["callout"]
    assert callout.attrs["detail"] == "4"
    assert callout.attrs["target_sheet"] == OWN_SHEET


def test_bubble_naming_another_sheet_beside_a_view_title_stays_a_callout():
    """A bubble beside a title that names a different sheet is a real cross-reference."""
    runs = view_with_number_bubble(title_x=160)
    found = symbols_of(runs, own_sheet="S40-07")
    assert found["view"][0].attrs["number"] == ""
    assert [c.attrs["target_sheet"] for c in found["callout"]] == [OWN_SHEET]


def test_example_set_views_are_numbered_and_no_sheet_calls_out_itself(platform):
    """Every view of the example set carries its bubble number, and none of those bubbles is left
    over as a callout from a sheet to itself."""
    assert all(v.attrs["number"] for v in platform.by_kind("view"))
    assert [v.attrs["number"] for v in platform.by_kind("view") if v.sheet == "S-301"] == ["1", "2", "3"]
    assert not [c.id for c in platform.by_kind("callout") if c.attrs["target_sheet"] == c.sheet]


# ---- grid bubbles -------------------------------------------------------------------------------
def test_grid_bubble_is_a_thin_round_circle_around_a_short_label():
    """Controls for the rejections below: each of these labels is a grid name in a drafted bubble."""
    found = symbols_of(
        [boxed("C", 300, 300, 312, 314), boxed("CP2", 500, 300, 518, 311), boxed("45", 900, 300, 911, 310)],
        circles=[circle(306, 307, 13, width=0.5), circle(509, 305, 20, width=0.5), circle(905, 305, 22, width=1.0)],
    )
    assert {g.attrs["name"] for g in found["grid"]} == {"C", "CP2", "45"}


def test_thick_stroked_circle_is_not_a_grid_bubble():
    """A heavy outline around a mark is a highlighted schedule cell, not a drafted bubble."""
    found = symbols_of([boxed("CP2", 500, 300, 518, 311)], circles=[circle(509, 305, 20, width=11.0)])
    assert found["grid"] == []


def test_elongated_outline_is_not_a_grid_bubble():
    """An oval around a centreline mark is not round, so it is not a grid bubble."""
    oval = Circle(bbox=(694, 292, 750, 320), arcs=4, width=1.0)
    found = symbols_of([boxed("CL", 700, 300, 712, 312)], circles=[oval])
    assert found["grid"] == []


def test_three_digit_number_in_a_circle_is_not_a_grid_name():
    """A bare three-digit number that happens to sit inside a circle reads as a dimension."""
    found = symbols_of([boxed("450", 900, 300, 916, 310)], circles=[circle(908, 305, 22, width=1.0)])
    assert found["grid"] == []


def test_number_in_a_callout_bubble_is_not_a_grid_name():
    """The top half of a callout bubble is a number in a circle, like a grid name; the sheet id
    written directly under it makes it a callout."""
    found = symbols_of(
        [boxed("4", 100, 200, 110, 210), boxed("S40-07", 86, 212, 124, 222)],
        circles=[circle(105, 211, 20, width=0.5)],
        own_sheet=OWN_SHEET,
    )
    assert found["grid"] == []
    assert [c.value for c in found["callout"]] == ["4/S40-07"]


# ---- revision table under column headers --------------------------------------------------------
def test_revision_table_with_column_headers_is_read_wherever_it_sits():
    """Some title sheets keep the revision history as a headed table (DATE / ISSUED FOR / REV) in
    the top margin, with the revision code in the last column, instead of numbered rows in the
    title strip. Rows are read by column, whatever the column order."""
    rows = [
        ("DATE", "ISSUED FOR", "REV"),
        ("2031-03-04", "Review", "B"),
        ("2031-09-17", "Fabrication", "1"),
    ]
    runs = []
    for i, (date, issued_for, rev) in enumerate(rows):
        y = 50 + 14 * i
        runs += [
            boxed(date, 400, y, 455, y + 10),
            boxed(issued_for, 460, y, 520, y + 10),
            boxed(rev, 580, y, 592, y + 10),
        ]
    parser = SheetParser(make_sheet(runs, width=612, height=792))
    parser.parse_revision_header_table()
    revisions = {f.attrs["number"]: f.attrs for f in parser.facts if f.kind == "revision"}
    assert set(revisions) == {"B", "1"}
    assert revisions["1"]["description"] == "Fabrication"
    assert revisions["1"]["date"] == "2031-09-17"
    assert revisions["B"]["description"] == "Review"
    assert parser._rev_table_found is True
