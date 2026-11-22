"""Question text handling shared by the rules: tokens, sheet and view names in a question, formatting."""

from __future__ import annotations

import re

from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.schema import Fact, Index

STOP = set(
    "the a an of in on at to for is are what what's which where how many much does do list show me give tell all any this that with and or from by please drawing drawings set sheet sheets their its it they them have has "
    "who whom whose should can could would will shall need needs i we you my our there here exist exists call".split()
)


SYN = {
    "thickness": "thick",
    "thicknesses": "thick",
    "anchors": "anchor",
    "bolts": "bolt",
    "welds": "weld",
    "plates": "plate",
    "columns": "column",
    "beams": "beam",
    "braces": "brace",
    "grades": "grade",
    "diameter": "dia",
    "dia.": "dia",
    "footing": "footing",
    "size": "size",
    "sizes": "size",
}


def tokens(q: str) -> list[str]:
    toks = re.findall(r"[a-z0-9][a-z0-9.\-\"']*", q.lower())
    out = []
    for t in toks:
        t = SYN.get(t, t)
        if t not in STOP and len(t) >= 2:
            out.append(t)
    return out


# A single rule answers one narrow thing; none of them compare values or answer several asks at once.
# If the question itself looks like it needs that, a rule's confidence in its own (partial) answer
# shouldn't be enough to skip the LLM.
RE_COMPOUND = re.compile(
    r"\band\s+(also|what|which|how|where|when|who|is|are|does|do)\b"
    r"|\?.*\?"
    r"|\b(compare[ds]?|compared to|versus|vs\.?|difference between)\b"
    r"|\b(thicker|thinner|greater|larger|smaller|heavier|lighter|more|less|higher|lower|deeper|wider|narrower)\s+than\b",
    re.I,
)


def is_compound(q: str) -> bool:
    """True if the question looks like it asks for several things or a comparison, not one lookup."""
    return bool(RE_COMPOUND.search(q))


def format_facts(facts: list[Fact], with_view=True) -> str:
    lines = []
    for f in facts:
        loc = f.sheet + (f" ({f.view})" if with_view and f.view else "")
        # a unit is added to a bare number only: "3'-6\"", "150mm" and "R50" carry theirs
        unit = (
            f" {f.unit}"
            if f.unit and f.kind in ("dimension", "elevation") and re.fullmatch(r"-?\d+(?:\.\d+)?", f.value.strip())
            else ""
        )
        note = ""
        if f.kind == "dimension":
            if f.attrs.get("chain_total"):
                note = f" — the overall of a string of {len(f.links)} dimensions that add up to it"
            elif f.attrs.get("chain_ok"):
                note = " — part of a string that adds up to an overall dimension"
        lines.append(f"- {f.value}{unit} — {loc}{note}")
    return "\n".join(lines)


# A sheet-number-shaped question token ("s13", "s.3", "c.0.5.2"): "is S13 referenced anywhere?" is about sheets
# even though S13 itself is not in the set.
RE_SHEETISH_TOK = re.compile(r"^[a-z]{1,2}[-.]?\d")


def named_views_in(q: str, idx: Index) -> set[str]:
    """View titles that appear verbatim in the question ("GP-07", "BRACED FRAME 3 (C-D)"). A title must contain a digit so that
    generic titles ("PLAN", "ELEVATION") never scope anything; the title minus a trailing "(...)" also counts."""
    ql = re.sub(r"\s+", " ", q.lower())
    out = set()
    for v in idx.by_kind("view"):
        t = (v.attrs.get("title") or "").strip()
        if not t or not re.search(r"\d", t):
            continue
        for cand in {t.lower(), re.sub(r"\s*\(.*\)\s*$", "", t.lower()).strip()}:
            if len(cand) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(cand)}(?![a-z0-9])", ql):
                out.add(t)
    return out


def named_sheet_in(toks: list[str], idx: Index) -> str | None:
    """If a token looks like one of this set's actual sheet numbers, return that sheet number so a
    lookup can be scoped to it — otherwise a well-matched note on some *other* sheet can crowd out
    a weaker-but-relevant hit on the sheet the question actually named."""
    for t in toks:
        if len(t) < 2 or not re.search(r"\d", t):
            continue
        for num in idx.sheet_numbers():
            if sheet_ref_matches(t.upper(), num):
                return num
    return None


def view_sort_key(v: Fact):
    n = v.attrs.get("number")
    try:
        return (0, int(n))
    except (TypeError, ValueError):
        return (1, str(n or ""))


def word_match(t: str, words: set[str]) -> bool:
    """A question token matches a fact word by 5-character prefix either way (plural/derived forms), except that a
    token of 3 or fewer letters ("dia", "bar") must match a whole word -- "dia" matched DIAPHRAGM and drowned the answer
    to "what is the pile diameter?"."""
    if len(t) <= 3:
        return any(w == t or (w.startswith(t) and not w[len(t)].isalpha()) for w in words)
    return any(w.startswith(t[:5]) or t.startswith(w[:5]) and len(w) >= 4 for w in words)
