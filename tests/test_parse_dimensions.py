"""Dimension values on hand-built sheets: which numbers over which lines are dimensions.

The usual case is small text over a hairline. These tests cover the edges: large text on details
drawn at a big zoom, thick dimension lines, and two numbers side by side that look like a numbered
note."""

from __future__ import annotations

from drawing_reader.parse import SheetParser
from support import make_run, make_sheet, segment

BASELINE = 300.0
LONG_HAIRLINE = (350, BASELINE + 4, 640, BASELINE + 4, 0.7)


def _number(text, size, x=400.0):
    """A number whose box stands on the baseline, about 0.6 of its size wide per character."""
    return make_run(text, x, BASELINE - size, size, x1=x + 0.6 * size * len(text), y1=BASELINE)


def _dimensions(runs, *lines):
    parser = SheetParser(make_sheet(runs, segments=[segment(*line) for line in lines]))
    parser.parse_dimensions()
    return [f.value for f in parser.facts if f.kind == "dimension"]


# --- large text -----------------------------------------------------------------------------------


def test_large_number_on_a_long_tight_hairline_is_a_dimension():
    """A detail drawn at a big zoom has 15-19 pt dimension text: accepted when a long hairline runs
    close under the whole number."""
    assert _dimensions([_number("520", 15.2)], LONG_HAIRLINE) == ["520"]
    assert _dimensions([_number("4275", 18.5)], LONG_HAIRLINE) == ["4275"]


def test_single_large_digit_is_not_a_dimension():
    """One digit at that size is a view or grid number, whatever line runs under it."""
    assert _dimensions([_number("2", 18.5)], LONG_HAIRLINE) == []


def test_large_number_over_a_line_barely_longer_than_itself_is_not_a_dimension():
    """A dimension line is several times longer than its number; a short stroke under big text is not one."""
    assert _dimensions([_number("520", 15.2)], (390, BASELINE + 4, 440, BASELINE + 4, 0.7)) == []


def test_large_number_far_above_a_line_is_not_a_dimension():
    """Big text must sit tight on its line: 50 pt above it is unrelated."""
    assert _dimensions([_number("520", 15.2)], (350, BASELINE + 50, 640, BASELINE + 50, 0.7)) == []


# --- thick lines ----------------------------------------------------------------------------------


def _small_number():
    return make_run("16500", 400, BASELINE - 8, 7.9, x1=440, y1=BASELINE)


def test_number_on_a_long_thick_line_is_a_dimension():
    """An overall dimension can be drawn on a heavy 3 pt line; with no hairline nearby it is used."""
    assert _dimensions([_small_number()], (350, BASELINE + 2, 640, BASELINE + 2, 3.0)) == ["16500"]


def test_number_over_a_short_thick_stub_is_not_a_dimension():
    """A short heavy stroke is a member outline, not a dimension line."""
    assert _dimensions([_small_number()], (390, BASELINE + 2, 450, BASELINE + 2, 3.0)) == []


def test_hairline_beside_a_thick_line_gives_one_dimension():
    """With a hairline and a thick line under the same number the value is read once."""
    lines = [(350, BASELINE + 2, 640, BASELINE + 2, 3.0), (350, BASELINE + 1, 640, BASELINE + 1, 0.7)]
    assert _dimensions([_small_number()], *lines) == ["16500"]


# --- two numbers that look like a numbered note ---------------------------------------------------


def test_two_numbers_on_one_baseline_are_dimensions_not_a_numbered_note():
    """ "50" followed by "250" on one baseline in one text block has the shape of note number 50 with
    the body "250", but a note body has at least one word: both are left for the dimension reader."""
    runs = [
        make_run("50", 400, BASELINE - 8, 8, x1=409, y1=BASELINE, block=3),
        make_run("250", 430, BASELINE - 8, 8, x1=444, y1=BASELINE, block=3),
    ]
    lines = [segment(380, BASELINE + 3, 425, BASELINE + 3), segment(425, BASELINE + 3, 470, BASELINE + 3)]
    parser = SheetParser(make_sheet(runs, segments=lines))
    parser.parse_notes()
    assert [f for f in parser.facts if f.kind == "note"] == []
    parser.parse_dimensions()
    assert sorted(f.value for f in parser.facts if f.kind == "dimension") == ["250", "50"]
