"""Acceptance questions: ask a drawing set a list of questions and score the answers.

A questions file is YAML:

    pdf: ../examples/access_platform_set.pdf     # relative to the questions file
    questions:
      - id: column-size                          # short, unique
        topic: members                           # free text, for grouping in the table
        q: What size are the columns?
        expect: [HSS152X152X9.5]                 # every string must be in the answer (case-insensitive)
        reject: [W310X39]                        # optional: none of these may be in it
        sheets: [S-201]                          # optional: the cited evidence must include these sheets
        method: rule:sections                    # optional: the answer must come from this rule (prefix)
        known_limit: why the reader gets it wrong   # optional: expected to fail today

A question passes when its answer contains every `expect` string, none of the `reject` strings,
cites evidence on every listed sheet and, when `method` is given, was produced by that rule. `method`
keeps a question from passing on the keyword fallback (`rule:text-search`), which lists matching
note lines instead of answering. A question marked `known_limit` is still asked and scored: it is
reported as "limit" while it fails and as "fixed" once it passes, so a limit is never hidden and a fix
is noticed. With no provider the run is deterministic: rules only, no network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from drawing_reader.ingest import ingest
from drawing_reader.parse import build_index
from drawing_reader.qa import Answer, answer
from drawing_reader.schema import Index


@dataclass
class Question:
    id: str
    q: str
    expect: list[str]
    topic: str = ""
    reject: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    method: str = ""
    known_limit: str = ""


@dataclass
class QuestionSet:
    pdf: Path
    questions: list[Question]
    source: Path


@dataclass
class Result:
    question: Question
    answer: Answer
    passed: bool
    problems: list[str]
    seconds: float

    @property
    def status(self) -> str:
        """pass | FAIL | limit (a known limit that still fails) | fixed (a known limit that now passes)."""
        if self.question.known_limit:
            return "fixed" if self.passed else "limit"
        return "pass" if self.passed else "FAIL"


def load_questions(path: str | Path) -> QuestionSet:
    """Read a questions file. Raises ValueError on a malformed file, naming what is wrong."""
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "pdf" not in data or not isinstance(data.get("questions"), list):
        raise ValueError(f"{path}: expected a mapping with 'pdf' and a 'questions' list")
    questions = []
    for n, item in enumerate(data["questions"], 1):
        unknown = set(item) - set(Question.__dataclass_fields__)
        if unknown or not {"id", "q", "expect"} <= set(item):
            raise ValueError(f"{path}: question {n} needs id, q and expect (unknown keys: {sorted(unknown)})")
        for key in ("expect", "reject", "sheets"):  # YAML reads 2030-05-08 as a date and 350 as a number
            item[key] = [str(v) for v in item.get(key) or []]
        questions.append(Question(**item))
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: question ids must be unique")
    return QuestionSet(pdf=(path.parent / data["pdf"]).resolve(), questions=questions, source=path)


def check(question: Question, ans: Answer) -> list[str]:
    """What is wrong with `ans` as an answer to `question`; empty when it passes."""
    text = ans.text.lower()
    problems = [f"missing {e!r}" for e in question.expect if e.lower() not in text]
    problems += [f"contains {r!r}" for r in question.reject if r.lower() in text]
    problems += [f"no evidence on {s}" for s in question.sheets if s not in ans.sheets]
    if question.method and not ans.method.startswith(question.method):
        problems.append(f"answered by {ans.method}, not {question.method}")
    return problems


def run_questions(question_set: QuestionSet, idx: Index, llm=None) -> list[Result]:
    results = []
    for question in question_set.questions:
        started = time.perf_counter()
        ans = answer(question.q, idx, llm=llm)
        problems = check(question, ans)
        results.append(Result(question, ans, not problems, problems, time.perf_counter() - started))
    return results


def evaluate(path: str | Path, cache_dir: str | Path, llm=None) -> tuple[Index, list[Result]]:
    """Index the questions file's drawing set and ask it every question."""
    question_set = load_questions(path)
    idx = build_index(ingest(question_set.pdf, cache_dir))
    return idx, run_questions(question_set, idx, llm)


def score(results: list[Result]) -> dict[str, int]:
    """Counts per status, plus `scored` (questions not marked as known limits) and `passed` of those."""
    counts = {status: sum(r.status == status for r in results) for status in ("pass", "FAIL", "limit", "fixed")}
    counts["scored"] = sum(not r.question.known_limit for r in results)
    counts["passed"] = counts["pass"]
    counts["total"] = len(results)
    return counts


def format_table(results: list[Result], details: bool = True, timing: bool = False) -> str:
    """A plain-text score table, one row per question, then the failures' details and a summary line."""
    rows = [("status", "id", "topic", "answered by", "conf") + (("time",) if timing else ())]
    for r in results:
        row = (r.status, r.question.id, r.question.topic, r.answer.method, f"{r.answer.confidence:.2f}")
        rows.append(row + ((f"{r.seconds:.2f}s",) if timing else ()))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip() for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    if details:
        for r in results:
            if r.status in ("FAIL", "limit"):
                lines.append("")
                lines.append(f"{r.status} {r.question.id}: {r.question.q}")
                if r.question.known_limit:
                    lines.append(f"  known limit: {r.question.known_limit}")
                lines.append(f"  problems: {'; '.join(r.problems)}")
                lines.append(f"  answer: {r.answer.text.replace(chr(10), ' | ')[:300]}")
    s = score(results)
    lines.append("")
    lines.append(
        f"{s['passed']}/{s['scored']} passed"
        + (f"; known limits: {s['limit']} still failing, {s['fixed']} now passing" if s["limit"] + s["fixed"] else "")
    )
    return "\n".join(lines)
