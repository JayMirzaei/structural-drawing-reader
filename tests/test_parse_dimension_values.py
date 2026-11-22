"""Dimensions: the text forms a value can take, strings of dimensions that add up, numbers set
inside their own dimension line, and the numbers that are not dimensions (table cells, bubbles,
negatives, ratios). Every input is invented."""

from __future__ import annotations

import pytest

from drawing_reader.parse.dimension_values import dimension_value
from drawing_reader.parse.sheet.parser import SheetParser
from support import circle, make_run, make_sheet, segment


def run(text, x0, y0, x1, y1, size, **kw):
    """A text run with an explicit box (x0, y0, x1, y1)."""
    return make_run(text, x0, y0, size, x1=x1, y1=y1, **kw)


def read_dimensions(runs, segments=(), circles=(), width=1224, height=792):
    """Parse only the dimensions of a hand-built sheet; returns {value: fact}."""
    parser = SheetParser(make_sheet(runs, segments, circles, width=width, height=height))
    parser.parse_dimensions()
    return {f.value: f for f in parser.facts if f.kind == "dimension"}


# --- text forms -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "millimetres", "kind"),
    [
        ("4200", 4200.0, "linear"),
        ("5'-3\"", 1600.2, "linear"),
        ("9'-0 1/2\"", 2755.9, "linear"),
        ("175mm", 175.0, "linear"),
        ("2.4 m", 2400.0, "linear"),
        ("R4.5", 4.5, "radius"),
        ("Ø32", 32.0, "diameter"),
        ("0.8", 0.8, "linear"),
    ],
)
def test_dimension_text_forms(text, millimetres, kind):
    """Bare millimetres, feet and inches (with a fraction), a value with its unit, a radius and a
    diameter are all dimension values, converted to millimetres."""
    value, _unit, found_kind = dimension_value(text)[:3]
    assert round(value, 1) == millimetres and found_kind == kind


def test_a_bare_number_takes_the_default_unit():
    assert dimension_value("4200")[:2] == (4200.0, "mm")


@pytest.mark.parametrize("text", ["3.6 kPa", "B14", "30°", "072", "000000"])
def test_values_that_are_not_lengths(text):
    """A pressure, a mark, an angle, and digit strings with a leading zero (a code, not a length)."""
    assert dimension_value(text) is None


@pytest.mark.parametrize(("read", "meant"), [("4'-7*", "4'-7\""), ("6'-0°", "6'-0\""), ("5'-3''", "5'-3\"")])
def test_a_misread_inch_mark_still_gives_the_length(read, meant):
    """A scan reads the inch mark as "*", a degree sign or two apostrophes."""
    assert dimension_value(read)[0] == dimension_value(meant)[0]


# --- dimension lines --------------------------------------------------------------------------------


def test_a_string_of_dimensions_is_checked_against_its_overall():
    """Three dimensions on one line and their overall on a parallel line: the parts are marked as
    adding up, and the overall links to them."""
    segments = [
        segment(120, 310, 370, 310, 0.5),
        segment(370, 310, 520, 310, 0.5),
        segment(520, 310, 920, 310, 0.5),
        segment(120, 260, 920, 260, 0.5),
    ]
    runs = [
        run("2500", 225, 295, 265, 307, 9),
        run("1500", 425, 295, 465, 307, 9),
        run("4000", 700, 295, 740, 307, 9),
        run("8000", 500, 245, 540, 257, 9),
    ]
    dims = read_dimensions(runs, segments)
    assert set(dims) == {"2500", "1500", "4000", "8000"}
    assert all(dims[v].attrs.get("chain_ok") for v in ("2500", "1500", "4000"))
    assert dims["8000"].attrs.get("chain_total")
    assert set(dims["8000"].links) == {dims[v].id for v in ("2500", "1500", "4000")}


def test_a_number_set_inside_its_own_broken_line_gets_that_line():
    """A dimension line broken around its number (horizontal), and a vertical line with an upright
    number over a gap in it: each number belongs to the line it interrupts, at the line's full length."""
    segments = [
        segment(120, 310, 212, 310, 0.5),
        segment(268, 310, 440, 310, 0.5),
        segment(640, 110, 640, 206, 0.5),
        segment(640, 215, 640, 330, 0.5),
    ]
    runs = [run("4800", 220, 305, 260, 315, 8), run("5500", 620, 206, 660, 215, 8)]
    dims = read_dimensions(runs, segments)
    assert set(dims) == {"4800", "5500"}
    assert all(f.attrs.get("inline") for f in dims.values())
    assert dims["4800"].attrs["line_length_pt"] == 320.0
    assert dims["5500"].attrs["line_length_pt"] == 220.0


def test_a_feet_inch_value_in_the_bottom_band_is_a_dimension_of_the_plan():
    """A plan can run into the band taken for the title block: a feet-inch value there is still a
    dimension, a bare number there stays with the title block."""
    runs = [run("31'-4\"", 566, 664, 598, 676, 8.0), run("31", 690, 664, 702, 676, 8.0)]
    assert list(read_dimensions(runs, width=842, height=700)) == ["31'-4\""]


# --- numbers that are not dimensions ------------------------------------------------------------------


def test_numbers_in_a_ruled_table_are_cells_not_dimensions():
    """A schedule with a rule above and below every row puts each number right under a line, like a
    dimension; the cells are left out and the real dimension beside the table is kept."""
    runs, segments = [], []
    for row in range(6):
        y = 110 + row * 14
        segments.append(segment(100, y - 2, 310, y - 2, 0.5))
        for col, x in enumerate((110, 170, 240)):
            text = f"B-{row:02d}" if col == 0 else str(3000 + 150 * row + col)
            runs.append(run(text, x, y, x + 36, y + 9, 8))
    segments.append(segment(100, 110 + 6 * 14 - 2, 310, 110 + 6 * 14 - 2, 0.5))
    runs.append(run("7200", 510, 405, 550, 415, 8))
    segments.append(segment(410, 420, 710, 420, 0.5))
    assert list(read_dimensions(runs, segments, width=792, height=612)) == ["7200"]


def test_aligned_numbers_without_row_rules_are_not_a_table():
    """Rows of numbers that line up, with no rules between them, are not taken for a ruled table."""
    runs = [
        run(str(1200 + 150 * row + col), 110 + 60 * col, 110 + 14 * row, 146 + 60 * col, 119 + 14 * row, 8)
        for row in range(5)
        for col in range(4)
    ]
    assert SheetParser(make_sheet(runs, width=792, height=612))._table_runs() == set()


def test_a_scanned_grid_of_numbers_without_rules_is_not_a_set_of_dimensions():
    """A table of coordinates read from a scan: several numbers per row, columns aligned to the
    pixel, the rules lost. None of it is a dimension."""
    runs = [
        run(str(4117 + row + 1000 * col), x, 110 + row * 14, x + 40, 120 + row * 14, 10.0, conf=0.9)
        for row in range(8)
        for col, x in enumerate((110, 170, 240, 310))
    ]
    assert read_dimensions(runs) == {}


@pytest.mark.parametrize("text", ["-212", "-03", "−4300"])
def test_a_number_with_a_leading_minus_is_not_a_dimension(text):
    """A length is never negative: an offset, or the tail of something cut at a dash, is no dimension."""
    line = [segment(94, 96, 164, 96, 0.5)]
    assert read_dimensions([run("1350", 104, 86, 128, 94, 8.0)], line, width=842, height=595).keys() == {"1350"}
    assert read_dimensions([run(text, 104, 86, 104 + 6 * len(text), 94, 8.0)], line, width=842, height=595) == {}


def test_the_number_after_a_slash_is_a_ratio_not_a_dimension():
    """ "L/360" read as "L/" and "360": a deflection limit in a note."""
    line = [segment(94, 96, 164, 96, 0.5)]
    runs = [run("L/", 92, 86, 102, 94, 8.0), run("360", 104, 86, 122, 94, 8.0)]
    assert read_dimensions(runs, line, width=842, height=595) == {}


def test_a_number_inside_a_small_circle_is_a_bubble_not_a_dimension():
    """A detail, section or keynote bubble sits above a line like a dimension does, but is no length."""
    number = run("52", 104, 86, 116, 94, 8.0)
    line = [segment(94, 96, 164, 96, 0.5)]
    assert list(read_dimensions([number], line, width=842, height=595)) == ["52"]
    bubble = [circle(110, 90, 10, width=0.3)]
    assert read_dimensions([number], line, bubble, width=842, height=595) == {}
