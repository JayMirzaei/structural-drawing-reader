"""Small behaviours: Markdown escaping, number checks, standards vs grades, heading case, location wording."""

from __future__ import annotations

import pytest

from drawing_reader.parse.materials import spec_role
from drawing_reader.parse.note_text import heading_case
from drawing_reader.providers.base import unsupported_numbers
from drawing_reader.qa import KIND_COLORS, answer, escape_markdown, safe_markdown
from support import make_fact


def test_markdown_escaping_keeps_text_and_drops_markup():
    hostile = "BOLTS ![x](https://example.invalid/t.png) <img src=x> *A325* # HEAD"
    escaped = escape_markdown(hostile)
    assert "![" not in escaped and "](" not in escaped and "<img" not in escaped.replace("\\<", "")
    assert escaped.replace("\\", "") == hostile  # nothing is lost, only escaped


def test_safe_markdown_keeps_only_our_scaffolding():
    text = "**Materials:** CSA G40.21 [see](x)\n- W310X39 *typ*\nplain <b>line</b>"
    out = safe_markdown(text).split("\n")
    assert out[0].startswith("**Materials:**") and "\\[see\\]\\(x\\)" in out[0]
    assert out[1].startswith("- W310X39 ") and "\\*typ\\*" in out[1]
    assert out[2] == "plain \\<b\\>line\\</b\\>"


def test_a_bolt_size_or_grade_is_checked_like_any_number():
    """Only the set's own sheet numbers and fact ids are skipped by the unsupported-number check."""
    fact = make_fact("S-501.note.001", "note", "BOLTS: M20 ASTM A325M", "S-501")
    known = {"S-501", "S-501.note.001"}
    assert unsupported_numbers("Bolts are M24 A490 (S-501.note.001, see S-501).", [fact], known) == ["24", "490"]
    assert unsupported_numbers("Bolts are M20 A325M, see 2/S-501.", [fact], known) == []
    assert unsupported_numbers("Bolts are M24 A490.", [fact]) == []  # without the set's refs: shape-based skip


@pytest.mark.parametrize(
    ("spec", "role"),
    [
        ("CSA G40.21 350W", "grade"),
        ("ASTM A325M", "grade"),
        ("ASTM A653", "grade"),
        ("CSA S16", "standard"),
        ("CSA S16-14", "standard"),
        ("CSA G164", "standard"),
        ("CSA W59", "standard"),
        ("ASTM A123 / A123M", "standard"),
        ("CSA S6", "standard"),
        ("CSA S60", "grade"),
        ("", ""),
    ],
)
def test_a_design_welding_or_coating_standard_is_not_a_grade(spec, role):
    assert spec_role(spec) == role


def test_grade_answers_leave_out_standards_and_a_standards_question_lists_them(platform):
    grade = answer("What is the steel grade of the beams?", platform)
    assert "G40.21" in grade.text and "G164" not in grade.text and "S16" not in grade.text
    standards = answer("What standards are cited?", platform)
    assert "CSA G164" in standards.text and "CSA S16" in standards.text and "F1554" not in standards.text


@pytest.mark.parametrize(
    ("text", "cased"),
    [("HSS COLUMNS", "HSS Columns"), ("ANGLES AND PLATES", "Angles And Plates"), ("OWSJ", "OWSJ"), ("BOLTS", "Bolts")],
)
def test_heading_case_keeps_acronyms(text, cased):
    assert heading_case(text) == cased


@pytest.mark.parametrize("question", ["What is the address?", "What is the location?", "Where is the project?"])
def test_the_bare_location_questions_reach_the_location_rule(platform, question):
    a = answer(question, platform)
    assert a.method == "rule:location" and "QUARRY ROAD" in a.text


def test_welds_can_be_drawn_as_an_overlay():
    assert "weld" in KIND_COLORS
