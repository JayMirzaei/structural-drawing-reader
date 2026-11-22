"""The scale measured from a view's own dimension strings, and the note that compares it with the
scale printed under the view title.

A dimension's printed value over the paper length of its line is a scale. The dimensions of one view
should mostly agree on it; the largest group that does is the view's measured scale."""

from __future__ import annotations

import pytest

from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.qa.rules.titleblock import _scale_note
from support import make_fact, make_sheet


def view_of(platform, title):
    return next(v for v in platform.by_kind("view") if v.attrs["title"] == title)


def measured_view(titled_scale: str, ratios: list[float]):
    """Run the consensus on one hand-built view whose dimensions measure the given scale ratios."""
    parser = SheetParser(make_sheet([]))
    view = parser._add("view", "NORTH ELEVATION", (100, 600, 260, 620), "NORTH ELEVATION", title="NORTH ELEVATION")
    view.attrs["scale"] = titled_scale
    for i, ratio in enumerate(ratios):
        box = (100 + 40 * i, 500, 120 + 40 * i, 510)
        parser._add("dimension", "1000", box, "1000", unit="mm", view="NORTH ELEVATION", scale_ratio=ratio)
    parser.assign_scale_consensus()
    return view


@pytest.mark.parametrize(
    ("title", "measured", "support"),
    [
        ("T.O. STEEL FRAMING PLAN", "1 : 50", "5/5"),
        ("ELEVATION ON GRID C", "1 : 50", "4/4"),
        ("ELEVATION ON GRID 1", "1 : 50", "3/3"),
        ("COLUMN BASE PLATE", "1 : 10", "8/8"),  # the hole diameter is not a length along a line: not counted
        ("BEAM TO COLUMN SHEAR TAB", "1 : 10", "5/5"),
    ],
)
def test_measured_scale_agrees_with_the_titled_scale(platform, title, measured, support):
    """On a set drawn to scale every view's dimensions land on the scale in its title: the
    measurement is a cheap agreement check, not a source of new numbers."""
    view = view_of(platform, title)
    assert view.attrs["scale_measured"] == measured
    assert view.attrs["scale_support"] == support
    assert _scale_note(view) == f" — dimension strings agree ({support})"


def test_a_view_without_dimension_lines_gets_no_measured_scale(platform):
    assert "scale_measured" not in view_of(platform, "ISOMETRIC VIEW").attrs


def test_a_tie_between_two_groups_is_broken_toward_the_titled_scale():
    """Two dimensions measure about 1:40 and two about 1:22. The titled scale decides between them."""
    view = measured_view("1 : 40", [22.0, 39.8, 22.3, 40.3])
    assert view.attrs["scale_measured"] == "1 : 40"
    assert view.attrs["scale_support"] == "2/4"


def test_a_tie_without_a_titled_scale_is_left_alone():
    """With no numeric title there is nothing to break the tie: no measured scale is claimed."""
    view = measured_view("N.T.S.", [22.0, 39.8, 22.3, 40.3])
    assert "scale_measured" not in view.attrs


def test_weak_agreement_that_differs_from_the_title_gives_no_warning():
    """Two of six dimensions agreeing on another scale is too little to contradict the title: the
    measurement is recorded, but the view is shown without a warning."""
    view = measured_view("1 : 25", [10.0, 10.1, 31.0, 47.0, 68.0, 90.0])
    assert view.attrs["scale_measured"] == "1 : 10"
    assert view.attrs["scale_support"] == "2/6"
    assert _scale_note(view) == ""


def scale_view(titled: str, measured: str, support: str):
    return make_fact(
        "S-301.view.001",
        "view",
        "BEARING DETAIL",
        "S-301",
        title="BEARING DETAIL",
        scale=titled,
        scale_measured=measured,
        scale_support=support,
    )


def test_scale_note_warns_from_four_of_six_dimensions():
    """Four of six dimensions (two thirds) agreeing on a scale more than a quarter away from the
    title is where the warning starts."""
    note = _scale_note(scale_view("1 : 20", "1 : 32", "4/6"))
    assert "check:" in note
    assert "1 : 32" in note
    assert "(4/6)" in note
    assert "titled 1 : 20" in note


def test_scale_note_does_not_warn_below_the_threshold():
    """Three of six is under the bar, and a measured scale within a quarter of the title is no
    contradiction either."""
    assert _scale_note(scale_view("1 : 20", "1 : 32", "3/6")) == ""
    assert _scale_note(scale_view("1 : 20", "1 : 24", "4/6")) == ""
