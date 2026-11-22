"""Title-block questions about one field: who drew or checked a sheet, its date, the project
number. Scoped to a named sheet, or grouped by value across the set."""

from __future__ import annotations

import pytest

from drawing_reader.qa import answer
from drawing_reader.schema import Index
from support import make_fact, make_index


def field(sheet: str, n: int, name: str, value: str):
    return make_fact(f"{sheet}.titleblock.{n:03d}", "titleblock", value, sheet, field=name)


@pytest.fixture
def two_sheets() -> Index:
    """Two sheets with the same drafter and project number, a different checker each, and a title
    block on S-101 that prints two dates (first issue and latest revision)."""
    return make_index(
        field("S-101", 1, "sheet_title", "FRAMING PLAN"),
        field("S-101", 2, "Checked By", "ALK"),
        field("S-101", 3, "Drawn By", "QEV"),
        field("S-101", 4, "Date", "2030-06-19"),
        field("S-101", 5, "Date", "2030-05-08"),
        field("S-101", 6, "Project No", "PN-4172"),
        field("S-201", 1, "sheet_title", "ELEVATIONS"),
        field("S-201", 2, "Checked By", "TMW"),
        field("S-201", 3, "Drawn By", "QEV"),
        field("S-201", 4, "Date", "2030-05-08"),
        field("S-201", 5, "Project No", "PN-4172"),
        sheets=["S-101", "S-201"],
        project={"Drawn By": "QEV", "Project No": "PN-4172", "Date": "2030-05-08"},
    )


def test_a_field_of_a_named_sheet(two_sheets):
    """'Who drew <sheet>?' cites that sheet's own Drawn By field: not the fields common to the set,
    not another sheet's title block."""
    a = answer("Who drew S-101?", two_sheets, llm=None)
    assert a.method == "rule:project"
    assert a.confidence >= 0.85
    assert "S-101" in a.text and "QEV" in a.text
    assert "S-201" not in a.text
    assert a.fact_ids == ["S-101.titleblock.003"]


def test_every_date_on_the_named_sheet_is_reported(two_sheets):
    """A title block with two dates gets both: the rule reports what is printed, it does not choose
    'the' date."""
    a = answer("What is the date of S-101?", two_sheets, llm=None)
    assert a.method == "rule:project"
    assert "2030-06-19" in a.text and "2030-05-08" in a.text
    assert set(a.fact_ids) == {"S-101.titleblock.004", "S-101.titleblock.005"}


def test_a_field_asked_for_the_whole_set_is_grouped_by_value(two_sheets):
    """With no sheet named, each distinct value gets its own row with the sheets that carry it: one
    sheet's checker is not swallowed by the other's."""
    a = answer("Who checked the drawings?", two_sheets, llm=None)
    assert a.method == "rule:project"
    assert a.confidence >= 0.8
    assert a.text.splitlines() == ["- Checked By: ALK — S-101", "- Checked By: TMW — S-201"]
    assert set(a.fact_ids) == {"S-101.titleblock.002", "S-201.titleblock.002"}


def test_the_project_number_is_answered_as_one_field(two_sheets):
    """'What is the project number?' gives that field with its citations, whichever label the title
    block uses for it, and none of the other fields common to the set."""
    a = answer("What is the project number?", two_sheets, llm=None)
    assert a.method == "rule:project"
    assert a.text == "- Project Number: PN-4172 — S-101, S-201"
    assert set(a.fact_ids) == {"S-101.titleblock.006", "S-201.titleblock.005"}


def test_a_field_missing_from_the_named_sheet_is_reported(two_sheets):
    """No title block here has a Client field. Asked for one sheet, the answer says so and does not
    fall back to other fields or another sheet."""
    a = answer("Who is the client for S-101?", two_sheets, llm=None)
    assert a.method == "rule:project"
    assert "No Client found in the title block of S-101" in a.text
    assert a.fact_ids == []


def test_drafter_of_one_sheet_and_of_the_set_on_the_example(platform):
    """The details sheet was drawn by someone else than the rest of the example set."""
    one = answer("Who drew S-301?", platform, llm=None)
    assert one.method == "rule:project"
    assert one.text == "Title block for S-301:\n- Drawn By: HZK"

    everyone = answer("Who drew the drawings?", platform, llm=None)
    assert everyone.text.splitlines() == ["- Drawn By: QEV — S-001, S-101, S-201, S-401", "- Drawn By: HZK — S-301"]
