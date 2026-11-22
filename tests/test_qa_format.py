"""How facts are written out in an answer: a unit is added to a bare number only, and dimensions
that were checked as a string say so."""

from __future__ import annotations

from drawing_reader.qa.text import format_facts
from support import make_fact


def dimension(fid, value, unit, **attrs):
    fact = make_fact(fid, "dimension", value, "S-101", **attrs)
    fact.unit = unit
    return fact


def test_a_unit_is_added_to_a_bare_number_only():
    """ "4200" needs its unit spelled out; "5'-3\\"" and "175mm" already carry theirs."""
    lines = format_facts(
        [
            dimension("S-101.dimension.001", "4200", "mm"),
            dimension("S-101.dimension.002", "5'-3\"", "ft-in"),
            dimension("S-101.dimension.003", "175mm", "mm"),
        ]
    ).split("\n")
    assert lines == ["- 4200 mm — S-101", "- 5'-3\" — S-101", "- 175mm — S-101"]


def test_a_unit_is_not_added_to_facts_that_are_not_measurements():
    label = make_fact("S-101.label.001", "label", "310", "S-101")
    label.unit = "mm"
    assert format_facts([label]) == "- 310 — S-101"


def test_a_part_of_a_checked_string_says_it_adds_up():
    line = format_facts([dimension("S-101.dimension.001", "2500", "mm", chain_ok=True)])
    assert line.startswith("- 2500 mm") and "adds up to an overall dimension" in line


def test_an_overall_dimension_says_how_many_parts_add_up_to_it():
    overall = dimension("S-101.dimension.004", "8000", "mm", chain_total=True)
    overall.links = ["S-101.dimension.001", "S-101.dimension.002", "S-101.dimension.003"]
    assert "the overall of a string of 3 dimensions" in format_facts([overall])


def test_the_view_is_named_beside_the_sheet_unless_switched_off():
    fact = dimension("S-101.dimension.001", "4200", "mm")
    fact.view = "FRAMING PLAN"
    assert format_facts([fact]) == "- 4200 mm — S-101 (FRAMING PLAN)"
    assert format_facts([fact], with_view=False) == "- 4200 mm — S-101"
