"""'What does note N say?': matching a numbered note by its number, its heading and its sheet.

Note numbers restart under every heading, so on the example set's notes sheet 'note 3' exists under
General Notes, Materials, Design Criteria and Structural Steel."""

from __future__ import annotations

from drawing_reader.qa import answer, answer_by_rules, tokens
from drawing_reader.qa.rules.notes import rule_note_lookup
from support import make_fact, make_index


def note_lookup(question, idx):
    """The note-lookup rule's own answer, whichever rule would win overall."""
    return next(a for a in answer_by_rules(question, idx) if a.method == "rule:note-lookup")


def cited_values(a, idx):
    return [idx.get(fid).value for fid in a.fact_ids]


def test_a_heading_word_selects_the_note_under_that_heading(platform):
    """'General note 3' is the third item under General Notes, and it wins outright."""
    a = answer_by_rules("What does general note 3 say?", platform)[0]
    assert a.method == "rule:note-lookup"
    assert cited_values(a, platform) == ["DO NOT SCALE THE DRAWINGS."]
    assert "[General Notes] note 3" in a.text
    assert a.confidence == 0.9


def test_another_heading_word_selects_another_note(platform):
    a = answer("What does materials note 5 say?", platform, llm=None)
    assert a.method == "rule:note-lookup"
    assert cited_values(a, platform) == ["BOLTS: M20 ASTM A325M UNO"]


def test_a_named_sheet_gives_every_note_with_that_number_on_it(platform):
    """Without a heading word, every 'note 3' on the named sheet is shown, at a lower confidence
    than a single match."""
    a = answer("What is note 3 on S-001?", platform, llm=None)
    assert a.method == "rule:note-lookup"
    headings = {platform.get(fid).attrs["heading"] for fid in a.fact_ids}
    assert headings == {"General Notes", "Materials", "Design Criteria", "Structural Steel"}
    assert len(a.fact_ids) == 4
    assert a.confidence == 0.85
    assert a.sheets == ["S-001"]


def test_a_number_missing_under_the_named_heading_is_reported(platform):
    """General Notes stops before 9, Materials has a note 9. The Materials note must not be given in
    its place: the answer says no note 9 exists under General Notes, and cites nothing."""
    a = answer("What does general note 9 say?", platform, llm=None)
    assert a.method == "rule:note-lookup"
    assert a.text == "No note 9 found under General Notes."
    assert a.fact_ids == []
    assert a.confidence == 0.8


def test_a_number_that_exists_nowhere_is_reported(platform):
    a = note_lookup("What does note 12 say?", platform)
    assert a.text == "No note 12 found."
    assert a.fact_ids == []
    assert a.confidence == 0.8


def test_a_number_missing_on_the_named_sheet_is_reported(platform):
    q = "note 2 on s-201?"
    a = rule_note_lookup(q, tokens(q), platform)
    assert a is not None
    assert a.text == "No note 2 found on S-201."
    assert a.confidence == 0.8


def test_fragments_that_share_a_note_number_are_never_shown_as_notes():
    """A weld tag or a run of dimension numbers can be filed under a note number by the parser. With
    fewer than three real words it is not a note, and is never returned as one."""
    weld_tag = make_fact("S-301.note.001", "note", "6 TYP.", "S-301", number="6", heading="")
    stray_numbers = make_fact("S-301.note.002", "note", "40 75 75", "S-301", number="40", heading="")
    real = make_fact("S-301.note.003", "note", "GRIND ALL EXPOSED WELDS SMOOTH.", "S-301", number="40", heading="")
    idx = make_index(weld_tag, stray_numbers, real, sheets=["S-301"])

    a = note_lookup("What does note 6 say?", idx)
    assert a.text == "No note 6 found."
    assert a.fact_ids == []

    b = note_lookup("What does note 40 say?", idx)
    assert b.fact_ids == ["S-301.note.003"]
    assert "40 75 75" not in b.text


def test_note_lookup_declines_a_sheet_that_is_not_in_the_set(platform):
    q = "what is note 4 on s-909?"
    assert rule_note_lookup(q, tokens(q), platform) is None


def test_note_lookup_declines_a_question_without_a_note_number(platform):
    q = "what do the notes say about welding?"
    assert rule_note_lookup(q, tokens(q), platform) is None
