"""Member designations and material clauses: which texts are member labels, how extended
designations are normalised, and how standards and yield strengths are read from notes."""

from __future__ import annotations

import pytest

from drawing_reader.parse import SheetParser
from drawing_reader.parse.materials import RE_ASTM, prose_yield_mpa
from drawing_reader.parse.members import parse_extended_member
from support import make_run, make_sheet


def _labels(*texts):
    """Member-label facts read from one sheet with the given texts stacked in a column."""
    runs = [make_run(text, 80, 120 + 24 * i, 7, x1=200) for i, text in enumerate(texts)]
    parser = SheetParser(make_sheet(runs))
    parser.parse_labels()
    return [f for f in parser.facts if f.kind == "label"]


# --- member labels --------------------------------------------------------------------------------


def test_hollow_sections_with_hs_and_ha_prefixes_are_hss_labels():
    """Square and round hollow sections written "HS..." and "HA..." belong to the HSS family, and
    the label keeps the prefix it was drawn with."""
    by_value = {f.value: f for f in _labels("HS152x152x9.5", "HA168x8.0")}
    assert by_value["HS152x152x9.5"].attrs["family"] == "HSS"
    assert by_value["HS152x152x9.5"].attrs["designation_prefix"] == "HS"
    assert by_value["HA168x8.0"].attrs["family"] == "HSS"


def test_paired_angles_carry_a_count_and_the_single_angle_section():
    """ "2-L..." and "2L..." are two angles: the count is kept apart from the section."""
    by_value = {f.value: f for f in _labels("2-L76x76x6.4", "2L102x102x13")}
    dashed = by_value["2-L76x76x6.4"]
    assert dashed.attrs["family"] == "L" and dashed.attrs["count"] == 2
    assert dashed.attrs["section"] == "L76x76x6.4"
    assert by_value["2L102x102x13"].attrs["count"] == 2


def test_bare_mark_and_count_before_a_non_angle_are_not_labels():
    """A short mark ("HS2") is not a section, and a count is only read in front of an angle."""
    assert _labels("HS2", "2 W250x58") == []


@pytest.mark.parametrize(
    ("text", "family", "section", "mark"),
    [
        ("W410X60TB3", "W", "W410X60", "TB3"),
        ("W200x27-", "W", "W200X27", None),
        ("*W310X39", "W", "W310X39", None),
        ("HSS6x6x3/8", "HSS", "HSS6X6X3/8", None),
        ("L21/2X2X1/4", "L", "L2-1/2X2X1/4", None),
        ("L3-1/2x3-1/2x5/16", "L", "L3-1/2X3-1/2X5/16", None),
        ("-PL152x76x9.5", "PL", "PL152X76X9.5", None),
        ("FB8x64", "FB", "FB8X64", None),
        ("*2L64X64X6.4 HB2", "L", "L64X64X6.4", "HB2"),
        ("[W530x92]", "W", "W530X92", None),
    ],
)
def test_extended_member_designations_are_normalised(text, family, section, mark):
    """A designation with a glued piece mark, stray punctuation, an imperial size or brackets is
    read as family, normalised section and mark."""
    got = parse_extended_member(text)
    assert got is not None
    assert got[0] == family and got[1] == section
    assert got[2].get("mark") == mark


@pytest.mark.parametrize("text", ["W310", "C250"])
def test_depth_without_a_mass_is_a_partial_designation(text):
    """A nominal depth alone ("W310") is a member, flagged as partial."""
    assert parse_extended_member(text)[2]["partial"]


@pytest.mark.parametrize(
    "text", ["W150 AND NOTES", "C3 & C4 = 4.8mm", "L2000-LINE", "S407", "M30172", "W305", "10 INCH SLAB"]
)
def test_marks_sheet_numbers_and_phrases_are_not_members(text):
    """A phrase, a schedule mark with a value, a line number, a sheet number, or a depth that is no
    standard series is not a member designation."""
    assert parse_extended_member(text) is None


def test_rods_pipes_and_joists_are_member_families():
    """A threaded rod, a pipe by outside diameter and schedule, and an open-web joist are read."""
    assert parse_extended_member('1-1/4"Ø ROD (Fy=36 ksi MIN)')[0] == "ROD"
    assert parse_extended_member('114.3 (4") SCH.40')[:2] == ("PIPE", "PIPE114.3 SCH40")
    assert parse_extended_member("18K4")[0] == "JOIST"


def test_extended_designations_become_labels_on_a_sheet():
    """The sheet parser turns extended designations into labels with their mark and partial flag."""
    by_section = {f.attrs["section"]: f for f in _labels("W410X60TB3", "HSS6x6x3/8", "W310")}
    assert set(by_section) == {"W410X60", "HSS6X6X3/8", "W310"}
    assert by_section["W310"].attrs["partial"]
    assert by_section["W410X60"].attrs["mark"] == "TB3"


# --- material clauses -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "spec"),
    [
        ("SHALL CONFORM TO CSA G40.21M300WT CATEGORY 2", "CSA G40.21M300WT"),
        ("CSA G40.21M-350W", "CSA G40.21M-350W"),
        ("WELD PER CSA W59", "CSA W59"),
    ],
)
def test_csa_citation_keeps_its_grade(text, spec):
    """A CSA steel citation is read with the grade glued to it; a standard with no grade is read as is."""
    assert RE_ASTM.search(text).group(1) == spec


def test_yield_strength_in_prose_prefers_the_mpa_value_given_in_brackets():
    """ "YIELD STRESS OF 60,000psi (420MPa)": the drawing's own MPa value is used."""
    assert prose_yield_mpa("MINIMUM YIELD STRESS OF 60,000psi (420MPa)") == ["420"]


def test_yield_strength_in_prose_is_read_in_mpa_or_converted_from_ksi():
    """An MPa value is taken as written; a ksi value with no MPa beside it is converted."""
    assert prose_yield_mpa("YIELD STRENGTH OF 345 MPa") == ["345"]
    assert prose_yield_mpa("YIELD STRESS 50 ksi") == ["345"]


def test_yield_strength_without_a_unit_is_not_guessed():
    """A bare number after "yield strength" has no unit, so no value is read."""
    assert prose_yield_mpa("YIELD STRENGTH OF 350") == []


def test_two_yield_statements_in_one_note_give_two_values():
    """Each yield statement in a clause gives its own value, in reading order."""
    text = (
        "MINIMUM YIELD STRESS FOR ANCHOR RODS SHALL BE 250 MPa. "
        "RODS MARKED HS SHALL HAVE A MINIMUM YIELD STRENGTH OF 725 MPa"
    )
    assert prose_yield_mpa(text) == ["250", "725"]


def test_note_with_a_prose_yield_strength_becomes_a_material_fact():
    """A numbered note that states a yield strength in words yields a material fact with fy."""
    note = "1. ANCHOR RODS SHALL BE THREADED, GRADE 55, MINIMUM YIELD STRESS OF 55,000psi (380MPa)."
    parser = SheetParser(make_sheet([make_run(note, 60, 120, 8, x1=560)]))
    parser.parse_notes()
    assert [f.attrs["fy_mpa"] for f in parser.facts if f.kind == "material"] == ["380"]
