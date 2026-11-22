"""A property every answering rule must keep: never confident and empty.

A rule may decline (return None) or answer with content. It must not return real confidence backed
by neither a cited fact nor an informative body: a header with nothing under it, a row of placeholder
dashes. A "not found" sentence is fine without a citation, because it says something. The rules are
probed with one question per rule family on indexes with little or nothing in them, which is where a
rule that only matched its trigger word shows itself.
"""

from __future__ import annotations

import re

import pytest

from drawing_reader.qa.router import RULES
from drawing_reader.qa.text import tokens
from drawing_reader.schema import Index, SheetMeta
from support import make_index

CONFIDENCE_FLOOR = 0.5
MIN_INFORMATIVE_CHARS = 20

PROBE_QUESTIONS = [
    "What is the project number of this set?",
    "Who is the client for the job?",
    "Which sheets are in the set?",
    "What scale is the drawing at?",
    "Which revision is the latest?",
    "Is S-101 referenced anywhere?",
    "Where is the bracing?",
    "Which column sections are used?",
    "Which grid lines are shown?",
    "At what angle is the brace?",
    "How thick is the base plate?",
    "What diameter are the anchor rods?",
    "Which welds are shown?",
    "Which views are on this sheet?",
    "How thick is the grout?",
    "What is the snow load?",
    "Are member forces shown anywhere?",
    "How many callouts does S-101 have?",
    "What is the elevation of the roof beam?",
    "Where is the site?",
    "What do the general notes say?",
    "What is the concrete strength?",
]


def is_informative(text: str) -> bool:
    """Long enough, and with real content after any "Header:" it opens with."""
    stripped = text.strip()
    if len(stripped) < MIN_INFORMATIVE_CHARS:
        return False
    body = re.sub(r"^[^:\n]*:\s*", "", stripped, count=1)
    return bool(re.search(r"[A-Za-z0-9]", body)) and body.strip(" -—–\n") != ""


def confidently_empty_answers(idx: Index) -> list[str]:
    """Every (rule, question) whose answer breaks the property, or that raised, on this index."""
    violations = []
    for question in PROBE_QUESTIONS:
        q = question.lower().strip()
        for rule in RULES:
            try:
                answer = rule(q, tokens(q), idx)
            except Exception as error:  # noqa: BLE001  a rule must not raise on a thin index either
                violations.append(f"{rule.__name__} raised {type(error).__name__} on {question!r}: {error}")
                continue
            if answer is None or answer.confidence < CONFIDENCE_FLOOR or answer.fact_ids:
                continue
            if not is_informative(answer.text):
                violations.append(f"{rule.__name__} on {question!r}: {answer.confidence} for {answer.text!r}")
    return violations


def empty_index() -> Index:
    return make_index(sheets=())


def bare_sheets_index() -> Index:
    """Two sheets with no title and no facts: some rules only engage once the set has sheets."""
    return make_index(sheets=[SheetMeta(page=1, number="S-101", title=""), SheetMeta(page=2, number="S-102", title="")])


@pytest.mark.parametrize("build", [empty_index, bare_sheets_index], ids=["no sheets", "bare sheets"])
def test_no_rule_is_confident_with_nothing_to_say_on_a_thin_index(build):
    assert confidently_empty_answers(build()) == []


def test_no_rule_is_confident_with_nothing_to_say_on_the_example_set(platform):
    """The same property on a full index: an uncited answer still has to say something."""
    assert confidently_empty_answers(platform) == []


def test_the_property_check_tells_content_from_placeholders():
    """The check itself: a bare header and a row of dashes are not content, a sentence is."""
    assert not is_informative("Title block (common to the set):\n")
    assert not is_informative("Client: — — — - - - - - - - -")
    assert not is_informative("No.")
    assert is_informative("No client was found in the title block of S-101.")
