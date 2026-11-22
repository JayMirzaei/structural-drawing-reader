"""Question answering over the fact index: deterministic rules first, an LLM provider second."""

from drawing_reader.qa.answer import MIN_CONFIDENCE, OCR_ANSWER_CAP, THRESHOLD, Answer
from drawing_reader.qa.evidence import KIND_COLORS, render_sheet
from drawing_reader.qa.markdown import escape_markdown, safe_markdown
from drawing_reader.qa.router import RULES, answer, answer_by_rules
from drawing_reader.qa.summary import first_look, scope_advice, text_layer_notice
from drawing_reader.qa.text import is_compound, tokens

__all__ = [
    "KIND_COLORS",
    "MIN_CONFIDENCE",
    "OCR_ANSWER_CAP",
    "RULES",
    "THRESHOLD",
    "Answer",
    "answer",
    "answer_by_rules",
    "escape_markdown",
    "first_look",
    "is_compound",
    "render_sheet",
    "safe_markdown",
    "scope_advice",
    "text_layer_notice",
    "tokens",
]
