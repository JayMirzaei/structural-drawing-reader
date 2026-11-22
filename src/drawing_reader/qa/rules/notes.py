"""Rules about note text: a numbered note, the general notes, and keyword search as the last resort."""

from __future__ import annotations

import re

from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.qa.answer import Answer, sheet_sort_key
from drawing_reader.qa.text import named_sheet_in, word_match
from drawing_reader.schema import Fact, Index

RE_NOTE_LOOKUP = re.compile(r"\b(?:note|clause|item)s?\s*(?:no\.?|number|#)?\s*(\d{1,3})\b")


# Words that talk *about* a note lookup rather than naming what the note is about -- must not
# count as a heading-filter word below (contrast "general"/"materials" in the docstring, which
# name real headings and must stay eligible). Deliberately does NOT special-case "general" in
# the regex above -- that would only handle the one literal word "general note N"; leaving it as
# an ordinary leftover token lets the same heading-matching mechanism scope "general note 5" to
# "General Notes" *and* "materials note 5" to "Materials" without two different code paths.
NOTE_LOOKUP_STOPWORDS = {
    "note",
    "notes",
    "clause",
    "clauses",
    "item",
    "items",
    "say",
    "says",
    "read",
    "state",
    "states",
    "text",
}


def note_lines(notes, limit=6) -> list[str]:
    lines = [f"- {f.value.strip()} — {f.sheet}" for f in notes[:limit]]
    if len(notes) > limit:
        lines.append(f"- …and {len(notes) - limit} more")
    return lines


def rule_general_notes(q, toks, idx: Index):
    """ "What are the general notes?" -- list the notes filed under a "General Notes" heading (the note
    text itself, not the heading lines a keyword search would return). Declines for a specific note
    number ("general note 5"), which rule_note_lookup answers exactly."""
    if not re.search(r"\bgeneral notes?\b", q) or RE_NOTE_LOOKUP.search(q):
        return None
    named_sheet = named_sheet_in(toks, idx)
    notes = [
        f
        for f in idx.by_kind("note")
        if f.attrs.get("heading", "").lower() == "general notes"
        and f.attrs.get("role") != "heading"
        and len([w for w in f.value.split() if re.search(r"[A-Za-z]{2,}", w)]) >= 4
    ]
    if named_sheet:
        notes = [f for f in notes if f.sheet == named_sheet]
    if not notes:
        return None
    return Answer(
        "General notes:\n" + "\n".join(note_lines(notes, 8)), [f.id for f in notes[:8]], 0.85, "rule:general-notes"
    )


def rule_note_lookup(q, toks, idx: Index):
    """A question naming a specific numbered note item ('note 5', 'general note 12', 'clause 3') is
    specific enough to match exactly on the note's own 'number' attr -- otherwise it falls to
    rule_text_search, where a bare number scores too low among keywords to win (MIN_CONFIDENCE), same
    failure mode rule_member_lookup fixed for member designations. The parser resets 'number' per
    heading section, so the same number can legitimately appear more than once even on one sheet
    (e.g. '1' under both 'General Notes' and 'Materials').

    Parser noise sharing a number with a real note -- a weld tag ("8 TYP.") or a stray dimension run
    ("47 154 154") -- has fewer than three words with a letter in them, and is excluded so it can
    never be returned as if it were a note. A leftover content word ("general", "materials") only
    narrows candidates down to a heading if that word actually names a heading *somewhere* in this
    index -- otherwise a typo or unrelated word would silently zero out every candidate. When it does
    name a real heading but this particular number doesn't exist under it (e.g. "general note 5" when
    General Notes only runs 1-4), that's reported as "not found under <Heading>" rather than falling
    back to some other heading's same-numbered note."""
    m = RE_NOTE_LOOKUP.search(q)
    if not m:
        return None
    num = m.group(1)

    named_sheet = named_sheet_in(toks, idx)
    if not named_sheet and any(re.fullmatch(r"[a-z]{1,2}[.\-]?\d+([.\-]\d+)?[a-z]?", t) for t in toks):
        return None  # names something sheet-shaped that isn't actually in this set

    all_notes = idx.by_kind("note")

    def _is_real(f: Fact) -> bool:
        return len([w for w in f.value.split() if re.search(r"[A-Za-z]", w)]) >= 3

    candidates = [
        f for f in all_notes if f.attrs.get("role") != "heading" and f.attrs.get("number") == num and _is_real(f)
    ]
    if named_sheet:
        candidates = [f for f in candidates if f.sheet == named_sheet]

    leftover = [
        t
        for t in toks
        if t not in NOTE_LOOKUP_STOPWORDS
        and not t.isdigit()
        and not (named_sheet and sheet_ref_matches(t.upper(), named_sheet))
    ]

    heading = None
    caveats = []
    if leftover:
        heading = next(
            (
                f.attrs["heading"]
                for f in all_notes
                if f.attrs.get("heading") and any(w in f.attrs["heading"].lower() for w in leftover)
            ),
            None,
        )
        if heading:
            candidates = [f for f in candidates if (f.attrs.get("heading") or "").lower() == heading.lower()]
        else:
            caveats = [f"No note heading matched '{' '.join(leftover)}'; showing every note {num}."]

    if not candidates:
        where = (f" under {heading}" if heading else "") + (f" on {named_sheet}" if named_sheet else "")
        return Answer(f"No note {num} found{where}.", [], 0.8, "rule:note-lookup")

    rows = [
        f"- {f.sheet} [{f.attrs.get('heading') or 'no heading'}] note {num}: {f.value}"
        for f in sorted(candidates, key=lambda f: (sheet_sort_key(f.sheet), f.attrs.get("heading") or ""))
    ]
    conf = 0.9 if len(candidates) == 1 else 0.85
    return Answer("\n".join(rows), [f.id for f in candidates], conf, "rule:note-lookup", caveats=caveats)


def rule_text_search(q, toks, idx: Index):
    """Keyword search over notes, materials, labels and loose text. Confidence scales with coverage."""
    if not toks:
        return None
    pool = idx.by_kind("note", "material", "text", "label", "elevation", "view")
    named_sheet = named_sheet_in(toks, idx)
    # a sheet-number token is a locator, not content -- score/cover on the rest of the question only,
    # so naming the sheet can't itself inflate or deflate the keyword-coverage confidence below.
    content_toks = [
        t
        for t in toks
        if not (
            len(t) >= 2
            and re.search(r"\d", t)
            and any(sheet_ref_matches(t.upper(), num) for num in idx.sheet_numbers())
        )
    ]
    scored = []
    df: dict[str, int] = {t: 0 for t in content_toks}  # how many facts each question word matches
    for f in pool:
        if f.attrs.get("role") == "heading":
            continue
        words = set(
            re.findall(r"[a-z0-9][a-z0-9.\-\"']*", (f.source_text + " " + (f.attrs.get("heading") or "")).lower())
        )
        hits = {t for t in content_toks if word_match(t, words)}
        for t in hits:
            df[t] += 1
        if hits:
            scored.append((len(hits), f, hits))
    scoped_to_sheet = False
    if named_sheet:
        on_sheet = [(n, f, h) for n, f, h in scored if f.sheet == named_sheet]
        if on_sheet:
            scored, scoped_to_sheet = on_sheet, True
    if not scored:
        return None
    scored.sort(key=lambda t: (-t[0], t[1].sheet))
    best = scored[0][0]
    sel, seen = [], set()
    for n, f, _h in scored:
        if n < max(1, best - 1) or len(sel) >= 8:
            break
        key = (f.sheet, f.value.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        sel.append(f)
    # Coverage weights each question word by rarity: a word found in over 10% of the facts ("foundation", "steel")
    # counts half, so "are there any piles in the foundation?" is judged on "piles" (rare) rather than diluted to 1/2.
    weight = {t: (0.5 if df[t] > 0.10 * max(1, len(pool)) else 1.0) for t in content_toks if len(t) > 2}
    best_hits = max((h for n, f, h in scored if n == best), key=lambda h: sum(weight.get(t, 0) for t in h))
    cover = sum(weight.get(t, 0) for t in best_hits) / max(1e-9, sum(weight.values())) if weight else 0
    if not weight:
        cover = best / max(1, len([t for t in content_toks if len(t) > 2]))
    conf = 0.8 if cover >= 0.99 and best >= 2 else (0.7 if cover >= 0.66 else (0.5 if cover >= 0.34 else 0.3))
    if scoped_to_sheet:
        # naming the right sheet is itself strong evidence, independent of how much of the rest of
        # the question's wording happens to also appear verbatim in that sheet's notes.
        conf = max(conf, 0.7)
    rows = [f"- “{f.value[:140]}” — {f.sheet}" + (f", {f.view}" if f.view else "") for f in sel]
    return Answer(
        "Closest matching text on the sheets:\n" + "\n".join(rows),
        [f.id for f in sel],
        conf,
        "rule:text-search",
        caveats=["Matched by keywords; read the highlighted text to confirm it answers the question."],
    )
