"""Scale, elevation and grout rules: scoping to a named sheet, yielding when there is nothing to
report, and flagging sheets that disagree."""

from drawing_reader.qa import answer
from drawing_reader.schema import SheetMeta
from support import make_fact, make_index


def grout_index(notes_value, detail_value):
    """A general note and a detail label that each state a grout thickness."""
    return make_index(
        make_fact("S-001.note.001", "note", f"GROUT: {notes_value}mm THICK UNDER ALL BASE PLATES", "S-001"),
        make_fact("S-301.text.001", "text", f"{detail_value}mm NON-SHRINK GROUT", "S-301"),
        sheets=("S-001", "S-301"),
    )


def test_grout_thickness_that_differs_between_sheets_is_flagged():
    """The general notes and a detail giving different grout thicknesses is a conflict to report,
    with each sheet's own value, not two search hits to list."""
    a = answer("Grout thickness?", grout_index(25, 30), llm=None)
    assert a.method == "rule:grout"
    assert "disagree" in a.text.lower()
    assert "S-001 says 25mm" in a.text and "S-301 says 30mm" in a.text
    assert a.fact_ids == ["S-001.note.001", "S-301.text.001"]


def test_grout_thickness_that_agrees_is_not_flagged():
    """The same value on both sheets is reported once per sheet without a warning."""
    a = answer("Grout thickness?", grout_index(30, 30), llm=None)
    assert a.method == "rule:grout"
    assert "disagree" not in a.text.lower()
    assert "- S-001: 30mm" in a.text and "- S-301: 30mm" in a.text


def test_scale_question_is_scoped_to_the_named_sheet():
    """'What is the scale of <sheet>?' answers with that sheet's scale, not every sheet's."""
    index = make_index(
        sheets=(
            SheetMeta(page=1, number="S-310", title="SECTIONS AND DETAILS", scale="1 : 25"),
            SheetMeta(page=2, number="S-120", title="ROOF FRAMING PLAN", scale="1 : 150"),
        )
    )
    a = answer("What is the scale of S-310?", index, llm=None)
    assert a.method == "rule:scale"
    assert "1 : 25" in a.text
    assert "S-120" not in a.text and "1 : 150" not in a.text


def test_scale_question_on_the_example_set_keeps_to_the_named_sheet(platform):
    """The details sheet is answered with its own sheet scale and its own three views."""
    a = answer("What is the scale of S-301?", platform, llm=None)
    assert a.method == "rule:scale"
    assert a.sheets == ["S-301"]
    assert "sheet scale 1:10" in a.text
    assert "1:50" not in a.text


def test_elevation_rule_yields_when_no_elevation_marker_was_read():
    """A set that states a level only in prose has no elevation facts: the rule must not answer
    with an empty list, so the note itself is found by the keyword search."""
    index = make_index(
        make_fact("S-001.note.001", "note", "UNDERSIDE OF BASE PLATE IS AT ELEVATION = 212.35", "S-001"),
        sheets=("S-001",),
    )
    a = answer("What is the elevation of the underside of base plate?", index, llm=None)
    assert a.method != "rule:elevations"
    assert "212.35" in a.text
