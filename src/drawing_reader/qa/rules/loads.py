"""Rules about design criteria: 'NAME = value' parameters, load tables, and saying when none are drawn."""

from __future__ import annotations

import re

from drawing_reader.qa.answer import Answer
from drawing_reader.qa.vocabulary import GENERIC_MATERIAL_WORDS, LOAD_TOPIC_WORDS
from drawing_reader.schema import Index

# design-criteria symbols are written "NAME = value unit" throughout general notes/typical details
# (snow/wind/seismic/soil parameters, connection forces) -- e.g. "Ss = 2.3 kPa", "Rd = 1.5",
# "Tf=30kN", "f'c = 30 MPa". Low noise on general notes.
# An optional parenthetical qualifier ("S (ULS)= 2.20 kPa", "S (SLS)= 1.60 kPa" -- combined-load-case
# results named alongside the base symbol) can sit between the symbol and "=" without changing what
# symbol is being defined.
# Units: kPa/kN/MPa/mm are matched case-insensitively ("2.15KPa", "MPA" are common in CAD text). The word
# boundary applies to the unit only, so the number group never backtracks to a prefix ("2.15KPa" is 2.15, not
# 1; "Vf = 0.4Vu = 145kN" is 145); `m`/`s` stay case-sensitive (a bare "M"/"S" after a value is not a unit).
_PARAM_UNIT = r"(?i:kPa|kN\s*[·.]?\s*m|kNm|kN(?:/m2?)?|MPa|mm)|m|s"


# `q` is an optional parenthetical qualifier -- a limit state ("S (ULS)") or a numeric period ("Sa(0.2)").
# not a fraction: t = 1/16"
RE_PARAM = re.compile(
    r"\b(?P<name>(?:f['’])?[A-Za-z]{1,4})\s*(?:\((?P<q>[A-Za-z]{2,5}|\d+(?:\.\d+)?)\))?\s*=\s*"
    r"(?P<val>-?\d+(?:\.\d+)?)(?!\s*/\s*\d)(?!\d)\s*(?:(?P<unit>" + _PARAM_UNIT + r")\b)?"
)


# A second, unrelated drafting convention for the same "name : value unit" design-criteria shape --
# a dotted leader instead of "=" ("LIVE LOAD..........................:3.6 kPa").
# The name here is a full phrase, not a short symbol, so it needs its own pattern rather
# than an alternative inside RE_PARAM's symbol group; merged with RE_PARAM's matches in rule_loads.
RE_PARAM_DOTTED = re.compile(
    r"\b(?P<name>[A-Za-z][A-Za-z /]{2,30}?)\s*\.{3,}\s*:?\s*(?P<val>-?\d+(?:\.\d+)?)\s*"
    r"(?:(?P<unit>" + _PARAM_UNIT + r")\b)?"
)


# Short enumerated design fields written "NAME: value" with no number or unit ("SITE CLASS: D").
RE_PARAM_FIELD = re.compile(
    r"\b(?P<name>SITE CLASS|IMPORTANCE CATEGORY|SEISMIC DESIGN CATEGORY|RISK CATEGORY)\s*[:=]\s*(?P<val>[A-Za-z0-9]{1,12})\b",
    re.I,
)


def rule_loads(q, toks, idx: Index):
    """Design-criteria values (snow/wind/seismic/soil parameters, connection forces) are written as
    'NAME = value unit' in the general notes and typical details; a bare keyword search only ever
    surfaces the prose sentence they sit in, never the number itself (see RE_PARAM). Also picks up
    `parse_load_table`'s structured label/value pairs ("LIVE LOAD" / "1.9 kPa" as
    two separate runs on the same row, a third convention neither RE_PARAM nor RE_PARAM_DOTTED
    covers), normalized to the same (name, value, unit) shape so both sources share one matching/
    output path."""
    pool = idx.by_kind("note", "text")
    all_matches = []
    for f in pool:
        # A single fact can bundle several unrelated "NAME = value" clauses (e.g. "a. Ss = 2.3 kPa
        # b. Sr = 0.1 kPa", or "Assume: Dead = 1.2kN Live = 3.6kPa") -- windowing each match's own
        # local context to the text between its neighboring matches (rather than the whole
        # `source_text`) stops one clause's topic word leaking into another's answer just because
        # they share a fact. `attrs["heading"]` is deliberately NOT windowed this way -- it already
        # classifies the whole fact under one topic on purpose (see the Ss/Sr snow-load test), so
        # every clause under a shared heading should keep matching that heading's topic.
        spans = sorted(
            [
                (m.start(), m.end(), m["name"], m["val"], m["unit"], m.groupdict().get("q"))
                for m in RE_PARAM.finditer(f.source_text)
            ]
            + [
                (m.start(), m.end(), m["name"], m["val"], m["unit"], None)
                for m in RE_PARAM_DOTTED.finditer(f.source_text)
            ]
            + [(m.start(), m.end(), m["name"], m["val"], None, None) for m in RE_PARAM_FIELD.finditer(f.source_text)]
        )
        # Text before the first clause ("SEISMIC: Rd = 2.0 Ro = 1.3") is the topic of *every* clause in an
        # unbroken list -- but not of a clause that follows its own words ("SNOW: Ss = 1.9 WIND: q = 0.38"),
        # so it is only shared with clauses whose gap to the previous clause has no word of its own.
        prefix = f.source_text[: spans[0][0]] if spans else ""
        for i, (start, _end, name, value, unit, qual) in enumerate(spans):
            win_start = spans[i - 1][1] if i > 0 else 0
            win_end = spans[i + 1][0] if i + 1 < len(spans) else len(f.source_text)
            gap = f.source_text[win_start:start]
            shared = prefix if i > 0 and not re.search(r"[A-Za-z]{4,}", gap) else ""
            ctx = f.source_text[win_start:win_end] + " " + shared + " " + (f.attrs.get("heading") or "")
            all_matches.append((f, name, value, unit, ctx, qual))
        if f.attrs.get("param_name"):
            ctx = f.source_text + " " + (f.attrs.get("heading") or "")
            all_matches.append((f, f.attrs["param_name"], f.attrs["param_value"], f.attrs.get("param_unit"), ctx, None))
    if not all_matches:
        return None
    all_names = {name.lower().lstrip("f'’") for _, name, _, _, _, _ in all_matches}
    # Strip the same leading f'/f' the stored names already had stripped -- otherwise "what is f'c"
    # captures "f'c" raw and can never match an all_names entry that was normalized to "c". A list
    # ("what are Rd and Ro?", "values of Ss, Sr") names several symbols at once.
    named_syms: set[str] = set()
    m_list = re.search(r"\b(?:what (?:is|are)|values? of)\s+(.+?)\s*\??\s*$", q)
    if m_list:
        for piece in re.split(r"\s*(?:,|&|\band\b)\s*", m_list.group(1)):
            piece = re.sub(r"^(?:the|its|their)\s+", "", piece.strip())
            piece = re.sub(r"\s*\([^)]*\)\s*$", "", piece)  # "sa(0.2)" -> "sa" (the qualifier narrows the rows below)
            if re.fullmatch(r"[a-z][a-z0-9']{0,4}", piece) and piece.lstrip("f'’") in all_names:
                named_syms.add(piece.lstrip("f'’"))
    # A multi-word structured name ("live load") named directly in the question is specific enough
    # to gate on by itself -- unlike the generic topic-word sweep below, this can't leak "dead load"
    # into a "live load" answer just because both mention "load" (LOAD_TOPIC_WORDS has no
    # "live"/"dead" entry). Checked by substring containment rather than reusing `named_sym`'s
    # "what is X" phrasing, since "what's the live load?" and "live load?" should both work too --
    # and containment is only safe here because these names have a space, unlike a bare 1-4 letter
    # symbol where "c" would match almost any question.
    named_multiword = {n for n in all_names if " " in n and n in q}
    # only the topic word(s) the question actually used -- not the whole master list, or a note
    # that happens to mention some *other* load topic (e.g. "seismic") leaks into a "snow" answer.
    # "load(s)" alone is too generic to discriminate -- every one of these clauses is *some* load
    # ("Snow Load", "Wind Loads"), so drop it whenever a more specific topic word is also present.
    topic_words = LOAD_TOPIC_WORDS & set(toks)
    match_words = (topic_words - {"load", "loads"}) or topic_words
    if not (named_syms or named_multiword or topic_words):
        return None
    # "Sa(0.2)" in the question narrows a symbol that appears for several periods/limit states to that one.
    asked_quals = {x.strip().lower() for x in re.findall(r"\(([^)]+)\)", q)}
    quals_by_name: dict[str, set[str]] = {}
    for _f, _n, _v, _u, _c, _q in all_matches:
        if _q:
            quals_by_name.setdefault(_n.lower().lstrip("f'’"), set()).add(_q.lower())
    rows, ids, seen = [], [], set()
    for f, name, value, unit, ctx, qual in all_matches:
        key_name = name.lower().lstrip("f'’")
        # A named multi-word entity ("live load") is a stronger, more specific signal than the
        # generic topic-word sweep -- skip that sweep entirely once one is named, or "load" (present
        # in every load-related row's ctx) would let "dead load" leak right back into a "live load"
        # answer despite named_multiword existing to prevent exactly that.
        if named_multiword:
            relevant = key_name in named_syms or key_name in named_multiword
        else:
            relevant = key_name in named_syms or (
                topic_words and any(re.search(rf"\b{w}\b", ctx, re.I) for w in match_words)
            )
            # "strength"/"concrete" alone are weak topics (f'c lists); when the question also names a subject
            # ("masonry grout", "slab", "pile") that the clause's own context never mentions, it is another
            # question's clause (grout compressive strength answered with concrete f'c rows).
            if relevant and key_name not in named_syms and match_words <= {"strength", "concrete"}:
                extra = [
                    t
                    for t in toks
                    if len(t) > 3
                    and t not in LOAD_TOPIC_WORDS
                    and t not in GENERIC_MATERIAL_WORDS
                    and t not in {"compressive", "design", "concrete", "specified", "mpa"}
                ]
                if extra and not all(re.search(rf"\b{re.escape(t.rstrip('s'))}", ctx, re.I) for t in extra):
                    relevant = False
        if not relevant:
            continue
        if (
            qual
            and key_name in named_syms
            and asked_quals & quals_by_name.get(key_name, set())
            and qual.lower() not in asked_quals
        ):
            continue
        val = f"{name}{f'({qual})' if qual else ''} = {value}" + (f" {unit}" if unit else "")
        key = (f.sheet, val)
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"- {val} — {f.sheet}")
        ids.append(f.id)
    if not rows:
        return None
    conf = 0.9 if (named_syms or named_multiword) else 0.8
    return Answer(
        "Design parameters found:\n" + "\n".join(rows),
        ids,
        conf,
        "rule:loads",
        caveats=["Extracted from 'NAME = value' style notes; check the highlighted text for full context."],
    )


RE_NO_LOADS_TRIGGER = re.compile(r"\b(force|forces|load|loads|reaction|reactions|kn|kpa)\b")


RE_NO_LOADS_YIELD = re.compile(r"\b(kN|kPa|force|forces|load|loads)\b", re.I)


def rule_no_loads(q, toks, idx: Index):
    """Convention assumed: on a structural set that states forces/loads at all, they show up in the
    extracted text either as a 'NAME = value' design parameter (RE_PARAM — snow/wind/seismic/soil
    criteria, connection forces) or as a bare kN/kPa/force/load mention in a note or text fact. If
    neither ever appears anywhere relevant to this question, the app must say so
    explicitly rather than falling through to the generic not-found text or a low-confidence,
    unrelated rule hit (e.g. rule_sections' member labels).

    A RE_PARAM match alone isn't enough to yield -- a material spec ('Fy=345 MPa') matches RE_PARAM
    too but has nothing to do with forces/loads, so this defers to rule_loads' own topic/symbol
    matching (not a second, looser reimplementation of it) to decide whether that content is
    actually relevant to what was asked."""
    if not RE_NO_LOADS_TRIGGER.search(q):
        return None
    if not idx.is_vector:
        return None
    if rule_loads(q, toks, idx) is not None:
        return None  # rule_loads has real, topic-relevant 'NAME = value' content to show
    pool = idx.by_kind("note", "text")
    if any(RE_NO_LOADS_YIELD.search(f.source_text) for f in pool):
        return None  # rule_text_search has a real kN/kPa/force/load mention to show
    return Answer(
        "No member forces or design loads are stated on this drawing set: no force or load value "
        "(kN, kPa, or a 'NAME = value' design parameter) appears anywhere in the extracted text, so "
        "force/load questions cannot be answered from these sheets.",
        [],
        0.85,
        "rule:no-loads",
        caveats=[
            "Checked the extracted text only; a force table drawn as graphics, or a scanned sheet, would not be detected."
        ],
    )
