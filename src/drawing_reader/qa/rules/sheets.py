"""Rules about the set itself: sheet lists, missing sheets, callouts and views."""

from __future__ import annotations

import re

from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.qa.answer import Answer, sheet_sort_key
from drawing_reader.qa.text import RE_SHEETISH_TOK, named_sheet_in, view_sort_key
from drawing_reader.qa.vocabulary import (
    GENERIC_CALLOUT_WORDS,
    GENERIC_SHEET_TOPIC_WORDS,
    GENERIC_VIEW_TOPIC_WORDS,
    SHEET_ABOUT_WORDS,
    SHEET_LISTING_WORDS,
)
from drawing_reader.schema import Fact, Index

# Drawing-set discipline letters (the usual NCS/CSA sheet-prefix convention) for "which sheets are structural?".
DISCIPLINE_PREFIX = {
    "structural": "S",
    "architectural": "A",
    "mechanical": "M",
    "electrical": "E",
    "civil": "C",
    "plumbing": "P",
    "landscape": "L",
}


RE_DISCIPLINE_Q = re.compile(
    r"\b(structural|architectural|mechanical|electrical|civil|plumbing|landscape)\b.{0,20}\bsheets?\b|"
    r"\bsheets?\b.{0,30}\b(structural|architectural|mechanical|electrical|civil|plumbing|landscape)\b"
)


def _discipline_listing(q: str, idx: Index):
    """ "Which sheets are structural?" on a combined set: the sheets whose number starts with that discipline's letter
    (S, A, M, E, C, P, L). Declines when no sheet carries the letter -- a set that numbers its structural sheets
    another way ("B.x") must not be told it has none."""
    m = RE_DISCIPLINE_Q.search(q)
    if not m:
        return None
    word = m.group(1) or m.group(2)
    letter = DISCIPLINE_PREFIX[word]
    sheets = [s for s in idx.sheets if s.number != f"P{s.page}" and re.match(rf"^{letter}[-.]?\d", s.number)]
    if not sheets:
        return None
    sheets.sort(key=lambda s: sheet_sort_key(s.number))
    others = len([s for s in idx.sheets if s not in sheets])
    rows = [f"- {s.number}: {s.title or '(no title found)'}" for s in sheets]
    head = f"{len(sheets)} {word} sheet(s) (numbers starting with {letter}), of {len(idx.sheets)} in the set:"
    nums = {s.number for s in sheets}
    ids = [f.id for f in idx.by_kind("sheet") if f.sheet in nums]
    return Answer(
        head + "\n" + "\n".join(rows),
        ids,
        0.85 if others else 0.7,
        "rule:sheets",
        caveats=[
            f"Discipline is read from the sheet-number prefix ({letter}); a set that numbers sheets another way is not classified."
        ],
    )


def rule_sheets(q, toks, idx: Index):
    if re.search(r"\b(missing|not in|referenced|not included|absent|revision|revisions|rev|issued|issue)\b", q):
        return None
    disc = _discipline_listing(q, idx)
    if disc:
        return disc
    # "What is the title of S.3?" / "What is on S.4?" don't contain the word "sheet" at all, so they'd
    # never reach the listing/topic-filter logic below -- a question that names one sheet and asks
    # about it in general (title/contents, no other topic word) gets a scoped one-sheet answer instead.
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        remainder = [t.rstrip(".") for t in toks if not sheet_ref_matches(t.upper(), named_sheet)]
        if all(t in SHEET_ABOUT_WORDS for t in remainder):
            meta = idx.sheet_by_number(named_sheet)
            title = (meta.title if meta else "") or "(no title found)"
            scale = meta.scale if meta else ""
            lines = [f"{named_sheet}: {title}" + (f" — scale {scale}" if scale else "")]
            views = sorted((v for v in idx.by_kind("view") if v.sheet == named_sheet), key=view_sort_key)
            lines += [f"- view {v.attrs.get('number', '')} {v.attrs.get('title', '')}" for v in views]
            kind_order = ("label", "dimension", "callout", "note", "elevation", "grid")
            counts = [
                (k, n) for k in kind_order if (n := sum(1 for f in idx.facts if f.sheet == named_sheet and f.kind == k))
            ]
            if counts:
                lines.append(f"Also indexed on {named_sheet}: " + ", ".join(f"{n} {k}(s)" for k, n in counts))
            ids = (
                [f.id for f in idx.by_kind("sheet") if f.sheet == named_sheet]
                + [
                    f.id
                    for f in idx.by_kind("titleblock")
                    if f.attrs.get("field") == "sheet_title" and f.sheet == named_sheet
                ]
                + [v.id for v in views]
            )
            return Answer("\n".join(lines), ids, 0.9, "rule:sheets")
    if not re.search(r"\b(sheets?|pages?|list of drawings|drawing list|how many drawings)\b", q):
        return None
    # "list the sheets" wants every sheet; "what sheets have masonry details" names a topic that
    # isn't a sheet property at all -- filtering by title (the only thing this rule can search)
    # keeps a topic-scoped question from returning the full, unfiltered list at 0.95 confidence.
    topic = [t for t in toks if len(t.rstrip(".")) > 3 and t.rstrip(".") not in SHEET_LISTING_WORDS]
    sheets, conf = idx.sheets, 0.95
    if topic:
        # Prefer specific topic words over generic sheet/view-type ones ("shear lug details"
        # shouldn't match on "details" alone -- that matched every "... DETAILS"-titled sheet in the
        # set even when none of them are actually about the other, more specific words asked for).
        # Falls back to the generic word(s) only when the question named nothing more specific.
        specific = [t for t in topic if t not in GENERIC_SHEET_TOPIC_WORDS] or topic
        matched = [s for s in sheets if any(t in (s.title or "").lower() for t in specific)]
        if not matched:
            return None
        sheets, conf = matched, 0.8
    if not sheets:
        return None  # "The set has 0 sheet(s)" is not an answer; let the other rules / "not found" speak
    nums = {s.number for s in sheets}
    rows = [
        f"- {s.number}: {s.title or '(no title found)'}" + (f" — scale {s.scale}" if s.scale else "") for s in sheets
    ]
    ids = [f.id for f in idx.by_kind("sheet") if f.sheet in nums] + [
        f.id for f in idx.by_kind("titleblock") if f.attrs.get("field") == "sheet_title" and f.sheet in nums
    ]
    head = f"{len(sheets)} sheet(s) match '{' '.join(topic)}':" if topic else f"The set has {len(sheets)} sheet(s):"
    return Answer(f"{head}\n" + "\n".join(rows), ids, conf, "rule:sheets")


def _missing_sheet_key(target_sheet: str) -> str:
    """Canonical form for grouping 'missing sheet' references -- the same dash/period/space
    insensitivity sheet_ref_matches' exact-match check uses, so 'S404' and 'S-404' (the same
    physical sheet, written two ways by different notes) group as one missing sheet instead of
    two double-counting the same real gap."""
    return re.sub(r"[.\s-]", "", target_sheet.upper())


def _group_missing_refs(refs: list[Fact]) -> tuple[dict[str, list[Fact]], dict[str, str]]:
    """Group missing-target reference/callout facts by canonical sheet key (_missing_sheet_key), so
    the same physical missing sheet spelled two ways (e.g. 'S404' / 'S-404') collapses into one
    group instead of double-counting the same real gap."""
    by_target: dict[str, list[Fact]] = {}
    display: dict[str, str] = {}  # canonical key -> the first-seen spelling, for display
    for f in refs:
        tgt = f.attrs["target_sheet"]
        key = _missing_sheet_key(tgt)
        by_target.setdefault(key, []).append(f)
        display.setdefault(key, tgt)
    return by_target, display


def _missing_rows(by_target: dict[str, list[Fact]], display: dict[str, str]) -> list[str]:
    rows = []
    for key, fs in sorted(by_target.items(), key=lambda kv: sheet_sort_key(kv[0])):
        where = ", ".join(sorted({f.sheet for f in fs}))
        ctx = fs[0].attrs.get("context") or fs[0].source_text
        rows.append(f"- {display[key]} — referenced on {where}: “{ctx[:90]}”")
    return rows


def rule_missing(q, toks, idx: Index):
    # "reference"/"referenced" alone also appear as an adjective/noun ("reference wind pressure", "referenced
    # standard") -- those only mean a sheet cross-reference when the question also talks about sheets/drawings/
    # details or names a sheet token; the unambiguous words (missing, absent, not in the set, cross-ref) always do.
    strong = re.search(r"\b(missing|not in the set|not included|absent|cross.?ref)\b", q)
    weak = re.search(r"\b(referenced|refers? to|references?)\b", q)
    sheetish = re.search(r"\b(sheets?|drawings?|dwgs?|details?|set|callouts?)\b", q) or any(
        RE_SHEETISH_TOK.match(t) for t in toks
    )
    if not (strong or (weak and sheetish)):
        return None
    if re.search(r"\bcallouts?\b", q):
        return None  # "how many callouts reference S50-01" asks rule_callouts's question, not this rule's
    have = idx.sheet_numbers()

    # A named *source* sheet ("which sheets referenced on S.3 are missing?") scopes to what that one
    # sheet references -- otherwise a real gap on some other sheet crowds out the narrower question.
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        # Direction: "referenced ON S.3" / "does S.3 reference..." asks what S.3 itself points to
        # (outgoing); "is S.3 referenced anywhere?" / "where is S.3 referenced?" asks whether OTHER
        # sheets point to it (incoming). These are different questions. The direction is read from the
        # text around the named sheet's token: preceded by "on"/"in", or followed by an active
        # "reference(s)", means outgoing; anything else (typically a passive "referenced" with the sheet
        # as its object) is incoming. When the token cannot be found verbatim, outgoing is assumed.
        outgoing = True
        sheet_tok = next((t for t in toks if sheet_ref_matches(t.upper(), named_sheet)), None)
        if sheet_tok:
            pos = q.find(sheet_tok)
            if pos >= 0:
                before, after = q[:pos], q[pos + len(sheet_tok) :]
                outgoing = bool(re.search(r"\b(on|in)\s*$", before)) or bool(
                    re.match(r"^\s*(reference|references|referencing)\b", after)
                )
        if not outgoing:
            incoming = [
                f
                for f in idx.by_kind("reference", "callout")
                if f.sheet != named_sheet and sheet_ref_matches(f.attrs.get("target_sheet", ""), named_sheet)
            ]
            if not incoming:
                return Answer(
                    f"No callouts or notes reference {named_sheet} anywhere in this set.", [], 0.85, "rule:missing"
                )
            citing = sorted({f.sheet for f in incoming}, key=sheet_sort_key)
            return Answer(
                f"{named_sheet} is referenced on: {', '.join(citing)}.", [f.id for f in incoming], 0.9, "rule:missing"
            )
        sheet_refs = [f for f in idx.by_kind("reference", "callout") if f.sheet == named_sheet]
        if not sheet_refs:
            return Answer(f"No callouts or sheet references found on {named_sheet}.", [], 0.8, "rule:missing")
        missing_here = [f for f in sheet_refs if not f.attrs.get("target_in_set", True)]
        if not missing_here:
            targets = sorted({f.attrs["target_sheet"] for f in sheet_refs}, key=sheet_sort_key)
            return Answer(
                f"Every sheet referenced on {named_sheet} is in the set "
                f"({named_sheet} references: {', '.join(targets)}).",
                [f.id for f in sheet_refs],
                0.85,
                "rule:missing",
            )
        by_target, display = _group_missing_refs(missing_here)
        rows = _missing_rows(by_target, display)
        txt = (
            f"{len(by_target)} referenced sheet(s) on {named_sheet} are not in this set "
            f"(set contains {', '.join(have)}):\n" + "\n".join(rows)
        )
        return Answer(txt, [f.id for f in missing_here], 0.9, "rule:missing")

    # A named *missing target* ("is S13 referenced anywhere?", "where is S7B referenced?") scopes to
    # that one target's group(s) instead of dumping every other unrelated gap alongside it. A
    # sheet-shaped token that matches neither a set sheet nor a known missing target yields (returns
    # None) rather than fabricating a "not referenced anywhere" answer this rule can't support.
    sheet_shaped = [t for t in toks if re.fullmatch(r"[a-z]{1,2}[.\-]?\d+([.\-]\d+)?[a-z]?", t)]
    if sheet_shaped:
        all_missing = [f for f in idx.by_kind("reference", "callout") if not f.attrs.get("target_in_set", True)]
        matched = [
            f for f in all_missing if any(sheet_ref_matches(t.upper(), f.attrs["target_sheet"]) for t in sheet_shaped)
        ]
        if not matched:
            return None
        by_target, display = _group_missing_refs(matched)
        rows = _missing_rows(by_target, display)
        if len(by_target) == 1:
            header = f"{next(iter(display.values()))} is referenced but not in this set:"
        else:
            header = (
                f"{len(by_target)} referenced sheet(s) matching your question are not in this set "
                f"(set contains {', '.join(have)}):"
            )
        return Answer(header + "\n" + "\n".join(rows), [f.id for f in matched], 0.9, "rule:missing")

    refs = [f for f in idx.by_kind("reference", "callout") if not f.attrs.get("target_in_set", True)]
    if not refs:
        allrefs = idx.by_kind("reference", "callout")
        return Answer(
            "Every sheet referenced by a callout or note is present in the set: "
            + ", ".join(dict.fromkeys(have))
            + ".",
            [f.id for f in allrefs],
            0.85,
            "rule:missing",
        )
    by_target, display = _group_missing_refs(refs)
    rows = _missing_rows(by_target, display)
    txt = f"{len(by_target)} referenced sheet(s) are not in this set (set contains {', '.join(have)}):\n" + "\n".join(
        rows
    )
    return Answer(txt, [f.id for f in refs], 0.9, "rule:missing")


def rule_callouts(q, toks, idx: Index):
    cos = idx.by_kind("callout")
    m_count = re.search(
        r"how many (?:detail |section )?callouts?\b(.*?)\b(s\s?[.\-]?\s?\d{1,3}[a-z]?(?:-\d{1,3}[a-z]?)?)\b", q
    )
    if m_count:
        between = m_count.group(1)
        tgt = m_count.group(2).replace(" ", "").upper()
        source_mode = re.search(
            r"\b(on|in|does|has|have|carry|carries|contain|contains|drawn|shown|placed|are there)\b", between
        ) and not re.search(
            r"\b(reference|references|referencing|refer|to|for|point|pointing|target|targeting|calling out|call out)\b",
            between,
        )
        if source_mode:
            sel = [c for c in cos if sheet_ref_matches(tgt, c.sheet)]
            refs = [f for f in idx.by_kind("reference") if f.attrs.get("detail") and sheet_ref_matches(tgt, f.sheet)]
            rows = [f"- {c.value} on {c.sheet}" for c in sel]
            rows += [
                f"- Detail {f.attrs['detail']}/{f.attrs['target_sheet']} mentioned in note text on {f.sheet}"
                for f in refs
            ]
            total = len(sel) + len(refs)
            return Answer(
                f"{total} callout(s) on {tgt}" + (":\n" + "\n".join(rows) if rows else "."),
                [c.id for c in sel] + [f.id for f in refs],
                0.85,
                "rule:callouts",
            )
        sel = [c for c in cos if sheet_ref_matches(tgt, c.attrs.get("target_sheet", ""))]
        refs = [
            f
            for f in idx.by_kind("reference")
            if f.attrs.get("detail") and sheet_ref_matches(tgt, f.attrs.get("target_sheet", ""))
        ]
        rows = [f"- {c.value} on {c.sheet}" for c in sel]
        rows += [
            f"- Detail {f.attrs['detail']}/{f.attrs['target_sheet']} mentioned in note text on {f.sheet}" for f in refs
        ]
        total = len(sel) + len(refs)
        return Answer(
            f"{total} callout(s) reference {tgt}" + (":\n" + "\n".join(rows) if rows else "."),
            [c.id for c in sel] + [f.id for f in refs],
            0.85,
            "rule:callouts",
        )
    m = re.search(
        r"\b(?:detail|section|sect\.?|elev(?:ation)?\.?)\s*([a-z]?\d{1,2}[a-z]?)\s*(?:/|on|of|,)?\s*(s\s?[.\-]?\s?\d{1,3}[a-z]?(?:-\d{1,3}[a-z]?)?)?",
        q,
    )
    if not m and not re.search(r"\b(callout|callouts|details? (are|is) (used|shown|referenced))\b", q):
        return None
    views = idx.by_kind("view")
    if m:
        num = m.group(1).upper()
        tgt = m.group(2).replace(" ", "").upper() if m.group(2) else None
        c_sel = [
            c
            for c in cos
            if c.attrs.get("detail") == num and (not tgt or sheet_ref_matches(tgt, c.attrs.get("target_sheet", "")))
        ]
        v_sel = [v for v in views if v.attrs.get("number") == num and (not tgt or sheet_ref_matches(tgt, v.sheet))]
        r_sel = [
            f
            for f in idx.by_kind("reference")
            if f.attrs.get("detail") == num and (not tgt or sheet_ref_matches(tgt, f.attrs.get("target_sheet", "")))
        ]
        if not c_sel and not v_sel and not r_sel:
            return None
        rows = [
            f"- Detail {num}/{c.attrs['target_sheet']} is called out on {c.sheet}"
            + (f" in view “{c.view}”" if c.view else "")
            for c in c_sel
        ]
        rows += [
            f"- The detail itself: view {v.attrs['number']} “{v.attrs['title']}” on {v.sheet}, scale {v.attrs['scale']}"
            for v in v_sel
        ]
        rows += [
            f'- Detail {num}/{f.attrs["target_sheet"]} is referenced in a note on {f.sheet}: "{f.attrs.get("context", "")}"'
            for f in r_sel
        ]
        return Answer(
            "\n".join(rows),
            [c.id for c in c_sel] + [v.id for v in v_sel] + [f.id for f in r_sel],
            0.85,
            "rule:callouts",
        )
    title_toks = [t for t in toks if t not in GENERIC_CALLOUT_WORDS]
    if title_toks:
        tset = set(title_toks)
        matched_views = [v for v in views if all(t in v.attrs.get("title", "").lower() for t in tset)]
        titles = {v.attrs.get("title", "").lower() for v in matched_views}
        if len(titles) == 1:
            keys = {(v.attrs.get("number"), v.sheet) for v in matched_views}
            c_sel = [c for c in cos if (c.attrs.get("detail"), c.attrs.get("target_sheet")) in keys]
            r_sel = [
                f for f in idx.by_kind("reference") if (f.attrs.get("detail"), f.attrs.get("target_sheet")) in keys
            ]
            total = len(c_sel) + len(r_sel)
            title = matched_views[0].attrs.get("title", "")
            rows = [f"- {c.value} on {c.sheet}" for c in c_sel]
            rows += [
                f"- Detail {f.attrs['detail']}/{f.attrs['target_sheet']} mentioned in note text on {f.sheet}"
                for f in r_sel
            ]
            return Answer(
                f"{total} callout(s) reference the {title.lower()}" + (":\n" + "\n".join(rows) if rows else "."),
                [c.id for c in c_sel] + [f.id for f in r_sel],
                0.8,
                "rule:callouts",
            )
    named_sheet = named_sheet_in(toks, idx)
    sel = [c for c in cos if c.sheet == named_sheet] if named_sheet else cos
    if named_sheet and not sel:
        return Answer(f"No detail callouts found on {named_sheet}.", [], 0.8, "rule:callouts")
    rows = [
        f"- {c.value} on {c.sheet}"
        + (f" ({c.view})" if c.view else "")
        + ("" if c.attrs.get("target_in_set") else "  ← target sheet not in set")
        for c in sel
    ]
    return Answer("Detail callouts:\n" + "\n".join(rows), [c.id for c in sel], 0.8, "rule:callouts")


def rule_views(q, toks, idx: Index):
    """'List the views on <sheet>' -- view titles are already extracted into 'view' facts (used by
    rule_scale and first_look), but nothing answered this directly; it fell through to rule_text_search,
    which only matches views whose title happens to contain a query keyword, not every view on the
    sheet asked about."""
    if not re.search(r"\bviews?\b", q):
        return None
    if "scale" in q:
        return None  # rule_scale owns scale questions, including ones that also mention "views"
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        sheet_views = sorted((v for v in idx.by_kind("view") if v.sheet == named_sheet), key=view_sort_key)
        if not sheet_views:
            return Answer(f"No view titles found on {named_sheet}.", [], 0.8, "rule:views")
        meta = idx.sheet_by_number(named_sheet)
        title = meta.title if meta else ""
        rows = [
            f"- view {v.attrs.get('number', '')} {v.attrs.get('title', '')} — scale {v.attrs.get('scale', '')}"
            for v in sheet_views
        ]
        header = f"{len(sheet_views)} view(s) on {named_sheet} ({title}):"
        return Answer(header + "\n" + "\n".join(rows), [v.id for v in sheet_views], 0.85, "rule:views")
    # no recognized sheet named, but a token still looks sheet-number-shaped (just not in this set) --
    # don't fall back to listing every view in the whole document as if no sheet had been asked about.
    if any(re.fullmatch(r"[a-z]{1,2}[.\-]?\d+([.\-]\d+)?[a-z]?", t) for t in toks):
        return None
    views = idx.by_kind("view")
    if not views:
        return None
    # A view described by its own title ("the cap plate at column top view"), not a sheet number --
    # same keyword-match rule_scale already does for its own unscoped path. Confidence high enough
    # to outrank rule_sections matching an incidental member-word inside that same title (e.g.
    # "column" in "CAP PLATE AT COLUMN TOP - PLAN VIEW").
    title_toks = [t for t in toks if len(t) > 3 and t not in GENERIC_VIEW_TOPIC_WORDS]
    specific = title_toks or [t for t in toks if len(t) > 3 and t != "view"]
    named = [v for v in views if any(t in (v.attrs.get("title") or "").lower() for t in specific)]
    if named:
        rows = [
            f"- {v.sheet} view {v.attrs.get('number', '')} {v.attrs.get('title', '')} — scale {v.attrs.get('scale', '')}"
            for v in named
        ]
        return Answer("\n".join(rows), [v.id for v in named], 0.9, "rule:views")
    by_sheet: dict[str, list[Fact]] = {}
    for v in views:
        by_sheet.setdefault(v.sheet, []).append(v)
    rows = []
    for s in sorted(by_sheet, key=sheet_sort_key):
        for v in sorted(by_sheet[s], key=view_sort_key):
            rows.append(
                f"- {s} view {v.attrs.get('number', '')} {v.attrs.get('title', '')} — scale {v.attrs.get('scale', '')}"
            )
    header = f"{len(views)} view(s) across {len(by_sheet)} sheet(s):"
    return Answer(header + "\n" + "\n".join(rows), [v.id for v in views], 0.8, "rule:views")
