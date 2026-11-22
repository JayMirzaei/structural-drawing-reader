"""Component properties written in note text ('25mm THICK', '450mm LONG', '20mm DIAMETER'), and
questions that ask for several properties of one component at once."""

from __future__ import annotations

import pytest

from drawing_reader.qa import THRESHOLD, answer, tokens
from drawing_reader.qa.rules.combined import rule_multi_property
from drawing_reader.qa.rules.materials import rule_component_spec
from support import make_fact, make_index

PLATE_NOTE, ROD_LENGTH_NOTE, ROD_DIAMETER_TEXT, GROUT_NOTE = (
    "S-301.note.901",
    "S-301.note.902",
    "S-301.text.903",
    "S-301.note.904",
)


@pytest.fixture(scope="module")
def detailed(platform):
    """The example set with four more lines of text on the details sheet, written the way many
    details state a component's properties: '<number><unit> <property>' after the component's name.
    The anchor lines say ANCHORS where a question would say 'anchor rods'."""
    idx = platform.model_copy(deep=True)
    lines = [
        (PLATE_NOTE, "note", "BASE PLATE: 25mm THICK", "COLUMN BASE PLATE"),
        (ROD_LENGTH_NOTE, "note", "ANCHORS: 450mm LONG, 75mm PROJECTION", "COLUMN BASE PLATE"),
        (ROD_DIAMETER_TEXT, "text", "ANCHORS: 20mm DIAMETER", "COLUMN BASE PLATE"),
        (GROUT_NOTE, "note", "GROUT: 25mm THICK, NON-SHRINK", None),
    ]
    for fid, kind, text, view in lines:
        fact = make_fact(fid, kind, text, "S-301")
        fact.view = view
        idx.facts.append(fact)
    return idx


def test_thickness_is_read_from_the_note_that_names_the_component(detailed):
    """A plate thickness stated only in note text is found, with the note as evidence."""
    a = answer("Base plate thickness?", detailed, llm=None)
    assert a.method == "rule:component-spec"
    assert a.confidence >= 0.85
    assert "25mm THICK" in a.text
    assert a.fact_ids == [PLATE_NOTE]
    assert a.sheets == ["S-301"]


def test_length_and_diameter_are_read_the_same_way(detailed):
    """'How long' and 'diameter' pick out the matching property span, in a note or in loose text."""
    length = answer("How long are the anchor rods?", detailed, llm=None)
    assert length.method == "rule:component-spec"
    assert "450mm LONG" in length.text
    assert "PROJECTION" not in length.text

    diameter = answer("Anchor rod diameter?", detailed, llm=None)
    assert diameter.method == "rule:component-spec"
    assert diameter.confidence >= THRESHOLD
    assert "20mm DIA" in diameter.text
    assert diameter.fact_ids == [ROD_DIAMETER_TEXT]


def test_size_and_thickness_of_one_component_are_merged(detailed):
    """'Size and thickness' of a plate spans two rules: its drawn dimensions and the thickness in
    the note. Neither rule alone answers both halves, so their answers are combined."""
    a = answer("Base plate size and thickness?", detailed, llm=None)
    assert a.method == "rule:multi-property"
    assert a.confidence == 0.85
    assert "350" in a.text and "25mm THICK" in a.text
    assert PLATE_NOTE in a.fact_ids
    assert any(fid.startswith("S-301.dimension.") for fid in a.fact_ids)
    assert a.sheets == ["S-301"]


def test_diameter_length_and_grade_are_merged_across_notes_and_materials(detailed):
    """Three properties, two rules: diameter and length come from the detail text, the grade from
    the materials list. The merged answer says that its parts differ in confidence."""
    a = answer("Anchor rod diameter, length, grade?", detailed, llm=None)
    assert a.method == "rule:multi-property"
    assert a.confidence >= THRESHOLD
    assert "20mm DIA" in a.text
    assert "450mm LONG" in a.text
    assert "ASTM F1554" in a.text
    assert {"S-001.material.004", ROD_LENGTH_NOTE, ROD_DIAMETER_TEXT} <= set(a.fact_ids)
    assert any("Combined from" in c for c in a.caveats)


def test_no_merge_when_one_rule_already_covers_every_property(detailed):
    """'Bolt size and grade' is answered in full by the materials list: merging would add nothing."""
    q = "bolt size and grade?"
    assert rule_multi_property(q, tokens(q), detailed) is None
    a = answer("Bolt size and grade?", detailed, llm=None)
    assert a.method == "rule:materials"
    assert a.confidence == 0.9
    assert "M20 ASTM A325M" in a.text


def test_no_merge_for_a_single_property(detailed):
    """A question naming one property stays with the rule that owns it, at that rule's confidence."""
    for q in ("base plate thickness?", "what is the base plate size?", "anchor rod diameter?"):
        assert rule_multi_property(q, tokens(q), detailed) is None

    thickness = answer("Base plate thickness?", detailed, llm=None)
    assert (thickness.method, thickness.confidence) == ("rule:component-spec", 0.85)
    size = answer("What is the base plate size?", detailed, llm=None)
    assert (size.method, size.confidence) == ("rule:dimensions", 0.85)
    diameter = answer("Anchor rod diameter?", detailed, llm=None)
    assert (diameter.method, diameter.confidence) == ("rule:component-spec", 0.75)


def test_property_words_do_not_count_as_part_of_the_component_name(detailed):
    """'Grade' and 'size' are properties other rules answer. They must not drag the match of the
    component's name below the bar, so this rule still covers every property it can read."""
    q = "anchor rod diameter, length, grade?"
    rods = rule_component_spec(q, tokens(q), detailed)
    assert rods is not None and rods.confidence == 0.75
    assert "450mm LONG" in rods.text and "20mm DIA" in rods.text

    q = "base plate size and thickness?"
    plate = rule_component_spec(q, tokens(q), detailed)
    assert plate is not None and plate.confidence == 0.85


def test_grout_and_plate_detail_thickness_belong_to_other_rules(detailed):
    """Grout thickness and the thickness of a plate labelled in a detail have their own rules; this
    one must not shadow them."""
    q = "grout thickness?"
    assert rule_component_spec(q, tokens(q), detailed) is None
    grout = answer("Grout thickness?", detailed, llm=None)
    assert grout.method == "rule:grout"
    assert "25mm" in grout.text

    gusset = answer("Gusset plate thickness at detail 3?", detailed, llm=None)
    assert gusset.method == "rule:sections"
    assert "thickness 10 mm" in gusset.text


def test_no_answer_without_a_property_word(detailed):
    """A question that names no thickness, length or diameter is not this rule's question."""
    q = "what are the column sections?"
    assert rule_component_spec(q, tokens(q), detailed) is None


def test_every_value_in_a_matched_note_is_listed():
    """One note can give the same property for two components. The rule lists every value in the
    note it matched instead of silently picking one: choosing between them needs interpretation."""
    body = "CAP PLATES ON HSS POSTS TO BE 12mm THICK, BASE PLATES UNDER HSS POSTS TO BE 25mm THICK"
    idx = make_index(make_fact("S-001.note.001", "note", body, "S-001"), sheets=["S-001"])
    a = answer("How thick are the post base plates?", idx, llm=None)
    assert a.method == "rule:component-spec"
    assert "12mm THICK" in a.text and "25mm THICK" in a.text
    assert a.text.count("- ") == 1
