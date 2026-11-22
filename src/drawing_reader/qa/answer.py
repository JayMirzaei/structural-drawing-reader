"""The answer object every rule and every LLM provider returns, and the confidence thresholds."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from drawing_reader.schema import Index

THRESHOLD = 0.75


OCR_ANSWER_CAP = 0.8  # answers citing OCR-read facts never exceed this (still above THRESHOLD: shown, with a caveat)


MIN_CONFIDENCE = 0.55  # below this, a rule "match" is too weak to show as an answer at all


@dataclass
class Answer:
    """What a rule or a provider returns.

    `sheets` always means "the sheets the cited evidence (`fact_ids`) is on". For "Is S30 referenced
    anywhere?" it lists the sheets that *reference* S30, not S30 itself. That differs from "the sheets
    this answer is about" whenever a question's subject and its evidence are in different places."""

    text: str
    fact_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "none"
    sheets: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def with_sheets(self, idx: Index) -> Answer:
        self.sheets = sorted({f.sheet for fid in self.fact_ids if (f := idx.get(fid))}, key=sheet_sort_key)
        return self


def sheet_sort_key(s: str):
    # Every numeric segment counts, not just the first: "C.0.5.10" sorts after "C.0.5.9", and "S3-10" after "S3-2".
    return (s[:1], tuple(int(x) for x in re.findall(r"\d+", s)), s)
