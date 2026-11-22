"""Scoring acceptance questions: the checks, the statuses and the table, on invented answers."""

from __future__ import annotations

import pytest

from drawing_reader.evaluation import (
    Question,
    Result,
    check,
    format_table,
    load_questions,
    run_questions,
    score,
)
from drawing_reader.qa import Answer
from support import ROOT


def result(passed: bool, known_limit: str = "", qid: str = "q1") -> Result:
    question = Question(id=qid, q="What?", expect=["x"], known_limit=known_limit)
    return Result(question, Answer("text", [], 0.9, "rule:test"), passed, [] if passed else ["missing 'x'"], 0.01)


def test_check_needs_every_expected_string_no_rejected_one_and_the_listed_sheets():
    question = Question(id="a", q="?", expect=["W310X39", "s-101"], reject=["W200X27"], sheets=["S-101"])
    good = Answer("Beams: W310X39 on S-101", ["f1"], 0.9, "rule:x", sheets=["S-101"])
    assert check(question, good) == []
    bad = Answer("Beams: W200X27", [], 0.9, "rule:x", sheets=["S-201"])
    assert check(question, bad) == [
        "missing 'W310X39'",
        "missing 's-101'",
        "contains 'W200X27'",
        "no evidence on S-101",
    ]


@pytest.mark.parametrize(
    ("passed", "known_limit", "status"),
    [(True, "", "pass"), (False, "", "FAIL"), (False, "why", "limit"), (True, "why", "fixed")],
)
def test_status_keeps_known_limits_apart(passed, known_limit, status):
    assert result(passed, known_limit).status == status


def test_score_counts_only_questions_that_are_not_known_limits():
    results = [result(True, qid="a"), result(False, qid="b"), result(False, "why", "c"), result(True, "why", "d")]
    assert score(results) == {"pass": 1, "FAIL": 1, "limit": 1, "fixed": 1, "scored": 2, "passed": 1, "total": 4}
    table = format_table(results)
    assert "1/2 passed; known limits: 1 still failing, 1 now passing" in table
    assert "FAIL b: What?" in table and "known limit: why" in table


def test_load_questions_resolves_the_pdf_and_reads_dates_and_numbers_as_text(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("pdf: set.pdf\nquestions:\n  - {id: d, q: 'When?', expect: [2030-05-08, 350]}\n")
    question_set = load_questions(path)
    assert question_set.pdf == tmp_path / "set.pdf"
    assert question_set.questions[0].expect == ["2030-05-08", "350"]


@pytest.mark.parametrize(
    "body",
    [
        "questions: []\n",
        "pdf: a.pdf\nquestions:\n  - {id: a, q: x}\n",
        "pdf: a.pdf\nquestions:\n  - {id: a, q: x, expect: [y], typo: 1}\n",
        "pdf: a.pdf\nquestions:\n  - {id: a, q: x, expect: [y]}\n  - {id: a, q: z, expect: [y]}\n",
    ],
)
def test_load_questions_rejects_malformed_files(tmp_path, body):
    path = tmp_path / "q.yaml"
    path.write_text(body)
    with pytest.raises(ValueError):
        load_questions(path)


def test_the_committed_question_files_are_well_formed():
    for name in ("questions.yaml", "questions_scan.yaml"):
        question_set = load_questions(ROOT / "eval" / name)
        assert question_set.pdf.is_file() and len(question_set.questions) >= 5


def test_rules_only_acceptance_run_on_the_example_set_has_no_unexpected_failure(platform):
    """Every acceptance question passes except the documented known limits; a fixed limit shows up too."""
    results = run_questions(load_questions(ROOT / "eval" / "questions.yaml"), platform)
    failing = [r.question.id for r in results if r.status == "FAIL"]
    fixed = [r.question.id for r in results if r.status == "fixed"]
    assert failing == [] and fixed == []


def test_rules_only_acceptance_run_on_the_scanned_sheet(platform_scan):
    results = run_questions(load_questions(ROOT / "eval" / "questions_scan.yaml"), platform_scan)
    assert [r.question.id for r in results if r.status in ("FAIL", "fixed")] == []
