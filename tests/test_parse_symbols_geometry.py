"""Drafting symbols read from geometry: grid bubbles, callout bubbles, elevation markers and
fillet weld glyphs. The size limits of each symbol follow the size of its own text, so a reduced
print and a full-size sheet are read by the same rule."""

from __future__ import annotations

from drawing_reader.parse import SheetParser
from drawing_reader.parse.index import _resolve_reference_targets
from support import circle, make_fact, make_index, make_run, make_sheet, segment


def _symbols(runs, circles=()):
    parser = SheetParser(make_sheet(runs, circles=circles))
    parser.parse_grids_callouts_elevations()
    return parser.facts


def _box(text, x0, y0, x1, y1, size):
    return make_run(text, x0, y0, size, x1=x1, y1=y1)


# --- grid bubbles ---------------------------------------------------------------------------------


def _grids(label_size, diameter):
    """Grid facts for a letter of the given text size centred in a circle of the given diameter."""
    half = label_size / 2
    label = _box("C", 300 - half, 200 - half, 300 + half, 200 + half, label_size)
    return [f.value for f in _symbols([label], [circle(300, 200, diameter / 2, width=0.25)]) if f.kind == "grid"]


def test_small_grid_bubble_on_a_reduced_print_is_read():
    """A 12 pt bubble around a 6 pt letter is a grid bubble: the lower limit follows the label size."""
    assert _grids(6, 12) == ["C"]


def test_full_size_grid_bubble_is_read():
    """The usual large bubble around a large letter is unchanged."""
    assert _grids(15, 32) == ["C"]


def test_circle_barely_larger_than_its_letter_is_not_a_grid_bubble():
    """A circle under 8 pt across is a dot or a bullet, not a bubble."""
    assert _grids(6, 7.5) == []


# --- callout bubbles ------------------------------------------------------------------------------


def _callouts(gap, size):
    """Callout facts for a detail number drawn `gap` points above a sheet id, both at text `size`."""
    number = _box("4", 300, 200, 300 + size, 200 + size, size)
    sheet_id = _box("S-501", 298, 200 + size + gap, 298 + 3.5 * size, 200 + 2 * size + gap, size)
    return [f.value for f in _symbols([number, sheet_id]) if f.kind == "callout"]


def test_callout_gap_allowance_scales_down_with_tiny_text():
    """On a much reduced print the number sits 1.4 pt above the sheet id at 2.6 pt text: still a callout."""
    assert _callouts(1.4, 2.6) == ["4/S-501"]


def test_callout_at_normal_text_size_is_read():
    """A number just above a sheet id at ordinary size is a callout."""
    assert _callouts(1.0, 10) == ["4/S-501"]


def test_number_far_above_a_sheet_id_is_not_its_callout():
    """A number several text heights above a sheet id does not belong to it."""
    assert _callouts(45, 10) == []


def test_callout_to_a_view_title_shaped_like_a_sheet_id_is_in_the_set():
    """A detail mark such as "3 / DB-04" can point at a view titled "DB-04" on another sheet: the
    target is in the set, and the sheet that holds the view is recorded."""
    idx = make_index(
        make_fact("S-301.callout.001", "callout", "3/DB-04", "S-301", target_sheet="DB-04"),
        make_fact("S-301.callout.002", "callout", "5/ZZ-77", "S-301", target_sheet="ZZ-77"),
        make_fact("S-403.view.001", "view", "DB-04", "S-403", title="DB-04"),
        sheets=("S-301", "S-403"),
    )
    _resolve_reference_targets(idx)
    found, missing = idx.facts[0], idx.facts[1]
    assert found.attrs["target_in_set"] is True
    assert found.attrs["target_view_sheet"] == "S-403"
    assert missing.attrs["target_in_set"] is False


# --- elevation markers ----------------------------------------------------------------------------


def _elevation_names(name, value):
    # the value is right-aligned under the name, as a level tag is drawn
    runs = [_box(name, 260 - 5 * len(name), 300, 260, 309, 8), _box(value, 260 - 5 * len(value), 310, 260, 318, 8)]
    return [f.attrs["name"] for f in _symbols(runs) if f.kind == "elevation"]


def test_punctuation_over_a_number_is_not_an_elevation():
    """A dash above a digit is not a level name with its value."""
    assert _elevation_names("-", "8") == []


def test_level_name_over_a_number_is_an_elevation():
    """A level name with its value under it is an elevation."""
    assert _elevation_names("LEVEL 3", "7200") == ["LEVEL 3"]


def test_short_level_mark_with_a_letter_and_a_digit_is_an_elevation_name():
    """A two-character mark ("T2") is enough of a name: a letter and two alphanumerics."""
    assert _elevation_names("T2", "7200") == ["T2"]


def _marked_elevations(size, gap, marker_diameter):
    """A level name over its value at text `size`, `gap` apart, with a marker circle beside them."""
    name = _box("Level 3", 800 - 6 * size, 250, 811, 250 + size, size)
    value = _box("7200", 811 - 2.4 * size, 250 + size + gap, 811, 250 + 2 * size + gap, size)
    radius = marker_diameter / 2
    marker = circle(816 + radius, 250 + size + radius, radius, width=0.3)
    facts = _symbols([name, value], [marker])
    return [(f.attrs["name"], f.value, f.attrs["has_marker"]) for f in facts if f.kind == "elevation"]


def test_elevation_marker_on_a_reduced_print_is_read():
    """At 3.8 pt text the value sits 2 pt under the name beside a 7 pt marker: still one elevation."""
    assert _marked_elevations(3.8, 2.0, 7.0) == [("Level 3", "7200", True)]


def test_elevation_marker_at_full_size_is_read():
    """The full-size convention (10 pt text, 22 pt marker) is unchanged."""
    assert _marked_elevations(10, 1.0, 22) == [("Level 3", "7200", True)]


def test_number_far_below_a_level_name_is_not_its_value():
    """A number three text heights under the name belongs to something else."""
    assert _marked_elevations(3.8, 13, 7.0) == []


# --- fillet weld symbols --------------------------------------------------------------------------


def _weld_sizes(leg, text_size):
    """Weld facts for a reference line carrying one right-triangle glyph with legs of `leg` points
    below it, and the size number "6" at `text_size` just left of the vertical leg."""
    x, y = 500, 300
    glyph = [
        segment(x, y, x + leg, y, 0.7),
        segment(x, y, x, y + leg, 0.7),
        segment(x, y + leg, x + leg, y, 0.7),
    ]
    middle = y + leg / 2
    number = _box("6", x - 1.5 - 0.5 * text_size, middle - text_size / 2, x - 1.5, middle + text_size / 2, text_size)
    parser = SheetParser(make_sheet([number], segments=glyph))
    parser.parse_welds()
    return [f.value for f in parser.facts if f.kind == "weld"]


def test_weld_glyph_with_short_legs_and_a_large_size_number_is_read():
    """A triangle with legs of about 10 pt beside a size number twice as tall is still a weld symbol."""
    assert _weld_sizes(10.5, 19) == ["6"]


def test_weld_glyph_of_the_usual_proportions_is_read():
    """A 22 pt triangle with a 10 pt size number is read."""
    assert _weld_sizes(22, 10) == ["6"]


def test_number_far_larger_than_the_triangle_is_not_its_weld_size():
    """A number four times the height of the triangle is some other text."""
    assert _weld_sizes(10.5, 42) == []


def test_reference_line_through_a_two_sided_glyph_is_one_weld_on_both_sides():
    """A reference line that runs on past two triangles sharing one vertical stem (one above the
    line, one below) is a single weld, marked as on both sides."""
    y, stem = 410.0, 480.0
    lines = [
        segment(450, y, 500, y, 0.5),
        segment(stem, y - 10.4, stem, y, 0.5),
        segment(stem + 9.4, y, stem, y - 10.4, 0.5),
        segment(stem, y + 10.4, stem, y, 0.5),
        segment(stem + 9.4, y, stem, y + 10.4, 0.5),
    ]
    number = _box("8", 454, y - 20.5, 465.5, y + 2, 20)
    parser = SheetParser(make_sheet([number], segments=lines))
    parser.parse_welds()
    welds = [(f.value, f.attrs["sides"]) for f in parser.facts if f.kind == "weld"]
    assert welds == [("8", "both")]
