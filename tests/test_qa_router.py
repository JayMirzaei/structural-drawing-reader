"""The router around the rules: what happens when the LLM fails, when nothing matches, when a
question has several parts, and how a named sheet scopes the keyword search and the sheet picker."""

from drawing_reader.providers.base import pick_sheets
from drawing_reader.qa import Answer, answer
from drawing_reader.qa.answer import THRESHOLD
from support import make_fact, make_index


class FailingLLM:
    """A provider whose call errors (quota, network, bad key)."""

    enabled = True

    def ask(self, question, idx, hint_ids=None, sheets=None):
        return Answer("The LLM call failed (ClientError).", [], 0.0, "llm:error", caveats=["ClientError: 401"])


def test_llm_failure_falls_back_to_the_weak_rule_answer(platform):
    """A rule answer below the confidence threshold is still better than an error: when the LLM
    call fails the rule answer is returned, with the failure recorded as a caveat."""
    question = "How many bolts hold the base plate?"
    rules_only = answer(question, platform, llm=None)
    assert rules_only.confidence < THRESHOLD  # otherwise the LLM would never be asked

    a = answer(question, platform, llm=FailingLLM())
    assert a.method == rules_only.method != "llm:error"
    assert "PL25X350X350" in a.text
    assert any("LLM call failed" in c and "ClientError: 401" in c for c in a.caveats)


def test_question_unrelated_to_the_drawings_says_not_found(platform):
    """Nothing on the sheets matches: the answer is an explicit 'not found' with zero confidence."""
    a = answer("What is the meaning of life?", platform, llm=None)
    assert a.method == "none"
    assert a.confidence == 0.0
    assert a.fact_ids == []


def test_multi_part_question_is_flagged_and_loses_confidence(platform):
    """One rule answers one thing: a question joined with 'and also' drops below the threshold
    (so an LLM gets to read it) and says why."""
    a = answer("What is the bolt grade and also what is the anchor rod diameter?", platform, llm=None)
    assert a.confidence < THRESHOLD
    assert any("multi-part or comparison" in c for c in a.caveats)


def test_keyword_search_keeps_to_the_sheet_named_in_the_question():
    """A well-matching note on another sheet must not outrank, or even accompany, the note on the
    sheet the question names."""
    index = make_index(
        make_fact(
            "S-001.note.001",
            "note",
            "WHERE A WELD IS NOT SHOWN IT SHALL BE CONTINUOUS FOR THE FULL LENGTH OF THE JOINT",
            "S-001",
        ),
        make_fact("S-310.note.001", "note", "SEAT ANGLE WELDED ALL AROUND TO HSS152X152X9.5", "S-310"),
        sheets=("S-001", "S-310"),
    )
    a = answer("What welds are shown on S-310?", index, llm=None)
    assert a.method == "rule:text-search"
    assert a.fact_ids == ["S-310.note.001"]
    assert "S-001" not in a.text

    unscoped = answer("What welds are shown?", index, llm=None)
    assert set(unscoped.fact_ids) == {"S-001.note.001", "S-310.note.001"}


def test_sheet_picker_prefers_a_title_match(platform):
    """A question word in a sheet's title outweighs the same word scattered in other sheets' text."""
    assert pick_sheets("elevations", platform)[0] == "S-201"
