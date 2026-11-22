"""Questions about members and drawn geometry: section labels, plate thickness in a detail, level
markers, grid bubbles and angle annotations, and how each is scoped to a sheet named in the question."""

from __future__ import annotations

import pytest

from drawing_reader.qa import answer, tokens
from drawing_reader.qa.rules.geometry import rule_grids
from drawing_reader.schema import Index
from support import make_fact, make_index


def label(fid: str, value: str, sheet: str, view: str | None = None, orientation: str = "horizontal", **attrs):
    family = "".join(ch for ch in value.split("X")[0] if ch.isalpha())
    fact = make_fact(fid, "label", value, sheet, family=family, orientation=orientation, section=value, **attrs)
    fact.view = view
    return fact


# ---- a bare designation ---------------------------------------------------------------------------


def test_a_bare_designation_is_looked_up_in_the_labels():
    """'Where is <section> used?' has one content word. Keyword search scores that too low to show,
    so an exact match on the member labels answers it."""
    idx = make_index(
        label("S-101.label.001", "W250X33", "S-101", view="PLATFORM FRAMING PLAN", orientation="vertical"),
        label("S-201.label.001", "HSS89X89X6.4", "S-201", orientation="diagonal"),
        sheets=["S-101", "S-201"],
    )
    a = answer("Where is W250X33 used?", idx, llm=None)
    assert a.method == "rule:member-lookup"
    assert "S-101" in a.text and "HSS89X89X6.4" not in a.text
    assert a.fact_ids == ["S-101.label.001"]


def test_a_designation_is_counted_per_sheet_on_the_example_set(platform):
    a = answer("Where is W200X27 used?", platform, llm=None)
    assert a.method == "rule:member-lookup"
    assert "2 label(s) on the drawings: S-101×2" in a.text
    assert a.sheets == ["S-101"]


# ---- section labels ---------------------------------------------------------------------------------


def test_sections_are_scoped_to_the_named_sheet(platform):
    """'Beam sections on <sheet>' lists that sheet's labels only, not every beam label in the set."""
    a = answer("What are the beam sections on S-201?", platform, llm=None)
    assert a.method == "rule:sections"
    assert a.sheets == ["S-201"]
    assert all(platform.get(fid).sheet == "S-201" for fid in a.fact_ids)
    assert "W310X39" in a.text
    assert "HSS152X152X9.5" not in a.text


def test_sections_says_so_when_the_named_sheet_has_none(platform):
    """A sheet without labels of the asked member type gets a plain 'none found', not other sheets'
    labels."""
    a = answer("What are the column sections on S-001?", platform, llm=None)
    assert a.method == "rule:sections"
    assert a.text == "No section labels for column found on S-001."
    assert a.fact_ids == []
    assert a.confidence == 0.8


def test_sections_without_a_sheet_cover_the_whole_set(platform):
    a = answer("What are the column sections?", platform, llm=None)
    assert a.method == "rule:sections"
    assert a.confidence == 0.85
    assert {"S-101", "S-201"} <= set(a.sheets)


# ---- plate thickness in a named detail ----------------------------------------------------------------


@pytest.fixture
def gussets() -> Index:
    """One detail sheet with three gusset types. Each has a bare 'PL t' thickness callout; two also
    have a side view with a separately sized 'PL AxBxC' plate."""
    return make_index(
        label("S-301.label.001", "PL10", "S-301", "GUSSET TYPE C4", thickness="10", plan=""),
        label("S-301.label.002", "PL10", "S-301", "GUSSET TYPE C5", thickness="10", plan=""),
        label("S-301.label.003", "PL420X180X8", "S-301", "GUSSET TYPE C5 - SIDE VIEW", thickness="8", plan="420X180"),
        label("S-301.label.004", "PL16", "S-301", "GUSSET TYPE C6", thickness="16", plan=""),
        label("S-301.label.005", "PL260X140X8", "S-301", "GUSSET TYPE C6 - SIDE VIEW", thickness="8", plan="260X140"),
        sheets=["S-301"],
    )


def test_plate_thickness_at_several_details_uses_every_detail_key(gussets):
    """A question naming three details gets the thickness callout of each, not only the first one
    named."""
    a = answer("Gusset plate thickness at C4, C5, C6?", gussets, llm=None)
    assert a.method == "rule:sections" and a.confidence == 0.85
    assert "PL10" in a.text and "PL16" in a.text
    views = {gussets.get(fid).view for fid in a.fact_ids}
    assert views == {"GUSSET TYPE C4", "GUSSET TYPE C5", "GUSSET TYPE C6"}


def test_plate_thickness_at_several_details_leaves_out_plan_size_plates(gussets):
    """The side-view plates share the detail keys but are other plates: only the bare thickness
    callouts are cited."""
    a = answer("Gusset plate thickness at C4, C5, C6?", gussets, llm=None)
    assert set(a.fact_ids) == {"S-301.label.001", "S-301.label.002", "S-301.label.004"}
    assert "PL420" not in a.text and "PL260" not in a.text


def test_plate_thickness_at_one_detail_gives_that_detail_only(gussets):
    """One detail key selects that detail's bare callout: no other detail, no plan-size plate."""
    a = answer("Gusset plate thickness at C6?", gussets, llm=None)
    assert a.method == "rule:sections" and a.confidence == 0.85
    assert a.fact_ids == ["S-301.label.004"]
    assert "thickness 16 mm" in a.text
    assert "PL10" not in a.text and "PL260" not in a.text


def test_plate_listing_is_not_narrowed_by_the_thickness_logic(gussets):
    """'What plates are shown' lists every plate on the sheet, plan-size ones included, and adds no
    thickness text."""
    a = answer("What plates are shown on S-301?", gussets, llm=None)
    assert a.method == "rule:sections"
    assert set(a.fact_ids) == {f.id for f in gussets.facts}
    assert "thickness" not in a.text


def test_plate_thickness_falls_back_to_a_plan_size_label():
    """When the named detail has only a 'PL AxBxC' label, its smallest number still answers the
    thickness question."""
    idx = make_index(
        label("S-301.label.001", "PL280X190X12", "S-301", "GUSSET TYPE C4", thickness="12", plan="280X190"),
        sheets=["S-301"],
    )
    a = answer("Gusset plate thickness at C4?", idx, llm=None)
    assert a.method == "rule:sections"
    assert a.fact_ids == ["S-301.label.001"]
    assert "thickness 12 mm, plan 280X190" in a.text


def test_plate_thickness_on_the_example_detail_sheet(platform):
    """The bare 'PL10 GUSSET' callout answers the gusset thickness; the sized base plate and shear
    tab on the same sheet are left out."""
    a = answer("Gusset plate thickness at detail 3?", platform, llm=None)
    assert a.method == "rule:sections"
    assert a.fact_ids == ["S-301.label.008"]
    assert "thickness 10 mm" in a.text and "PL25" not in a.text


# ---- level markers ------------------------------------------------------------------------------------


def level(fid: str, name: str, value: str, sheet: str):
    return make_fact(fid, "elevation", value, sheet, name=name, has_marker=True)


@pytest.fixture
def levels() -> Index:
    """Two elevation sheets. T.O. STEEL repeats on both; the hopper beam level is on S-202 only. The
    beam labels give the section rule something to answer with, if it were to win."""
    return make_index(
        level("S-201.elevation.001", "L2", "4200", "S-201"),
        level("S-201.elevation.002", "T.O. CRANE GIRDER", "7350", "S-201"),
        level("S-201.elevation.003", "T.O. STEEL", "8900", "S-201"),
        level("S-202.elevation.001", "T.O. STEEL", "8900", "S-202"),
        level("S-202.elevation.002", "U/S HOPPER BEAM", "5150", "S-202"),
        label("S-201.label.001", "W460X74", "S-201"),
        label("S-202.label.001", "W310X39", "S-202"),
        sheets=["S-201", "S-202"],
    )


def test_levels_are_scoped_to_the_named_sheet(levels):
    """Level names repeat across sheets. 'What elevations are on <sheet>?' lists that sheet's
    markers and nothing that exists only on another sheet."""
    a = answer("What elevations are on S-201?", levels, llm=None)
    assert a.method == "rule:elevations"
    assert a.sheets == ["S-201"]
    assert "HOPPER BEAM" not in a.text
    assert "T.O. STEEL: 8900" in a.text


def test_levels_says_so_when_the_named_sheet_has_none(platform):
    """A sheet with no level markers gets a plain 'none found', not the markers of other sheets."""
    a = answer("What elevations are on S-101?", platform, llm=None)
    assert a.method == "rule:elevations"
    assert a.text == "No elevation markers found on S-101."
    assert a.confidence == 0.8
    assert a.fact_ids == []


def test_levels_named_exactly_and_loosely_are_all_answered(levels):
    """A question with three targets, one matching a marker name exactly and two only by a word of
    the name, gets all three: the exact hit must not discard the loose ones."""
    a = answer("Elevation of level L2 / crane girder / hopper beam?", levels, llm=None)
    assert a.method == "rule:elevations"
    assert a.confidence == 0.85
    assert "L2: 4200" in a.text
    assert "T.O. CRANE GIRDER: 7350" in a.text
    assert "U/S HOPPER BEAM: 5150" in a.text
    assert "T.O. STEEL" not in a.text


def test_plural_elevations_is_a_level_question_not_a_section_question(levels):
    """'Elevations of ... the hopper beam' names a beam but asks for levels: the level rule wins
    over the section-label rule."""
    a = answer("What are the elevations of L2, the crane girder and the hopper beam?", levels, llm=None)
    assert a.method == "rule:elevations"


def test_one_named_level_gives_one_row(levels):
    a = answer("What is the elevation of L2?", levels, llm=None)
    assert a.method == "rule:elevations"
    assert "L2: 4200" in a.text
    assert "BEAM" not in a.text and "GIRDER" not in a.text


def test_levels_on_the_example_elevation_sheet(platform):
    a = answer("What elevations are on S-201?", platform, llm=None)
    assert a.method == "rule:elevations"
    assert a.sheets == ["S-201"]
    for row in ("T.O. SLAB: 0 mm", "T.O. STEEL: 3600 mm", "T.O. GUARD: 4700 mm"):
        assert row in a.text


# ---- grid bubbles and angles ----------------------------------------------------------------------------


def test_grids_are_scoped_to_the_named_sheet(platform):
    """'Which grids are on <sheet>?' cites that sheet's bubbles only."""
    a = answer("Which grids are on S-201?", platform, llm=None)
    assert a.method == "rule:grids"
    assert a.sheets == ["S-201"]
    assert len(a.fact_ids) == 5
    assert sorted(platform.get(fid).attrs["name"] for fid in a.fact_ids) == ["1", "2", "A", "B", "C"]

    none_here = answer("Which grids are on S-001?", platform, llm=None)
    assert none_here.text == "No grid bubbles found on S-001."


def test_grids_rule_yields_when_the_set_has_no_bubbles():
    """With no grid facts at all the rule steps aside instead of reporting an empty list."""
    q = "what grid lines are there?"
    assert rule_grids(q, tokens(q), make_index(sheets=["S-101", "S-201"])) is None


def test_angles_are_scoped_to_the_named_sheet(platform):
    """'Brace angles on <sheet>' answers from that sheet only, and says so when it has none."""
    none_here = answer("What are the brace angles on S-101?", platform, llm=None)
    assert none_here.method == "rule:angles"
    assert none_here.text == "No angle annotations found on S-101."
    assert none_here.fact_ids == []

    detail = answer("What are the brace angles on S-301?", platform, llm=None)
    assert detail.method == "rule:angles"
    assert detail.fact_ids == ["S-301.angle.001"]
