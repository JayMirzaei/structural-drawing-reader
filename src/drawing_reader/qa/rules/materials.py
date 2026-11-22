"""Rules about materials and component properties stated in notes: grades, grout, concrete, sizes."""

from __future__ import annotations

import re

from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.qa.answer import Answer, sheet_sort_key
from drawing_reader.qa.rules.notes import note_lines
from drawing_reader.qa.text import RE_SHEETISH_TOK, named_sheet_in, word_match
from drawing_reader.qa.vocabulary import COMPONENT_PROPERTY_TOKENS, GENERIC_MATERIAL_WORDS, MATERIAL_COMPONENT_SYNONYMS
from drawing_reader.schema import Index

RE_STANDARD_Q = re.compile(r"\b(standards?|codes?|galvani[sz]\w*|coating|weld\w*|electrodes?|design)\b")


def rule_materials(q, toks, idx: Index):
    grade_hit = re.search(r"\b(grade|grades|fy|astm|csa|material|materials|steel grade|yield|standards?)\b", q)
    size_hit = re.search(r"\b(size|sizes|dia\.?|diameter|diameters)\b", q)
    if not grade_hit and not size_hit:
        return None
    mats = idx.by_kind("material")
    if not mats:
        return None
    standards = [m for m in mats if m.attrs.get("role") == "standard"]
    asks_standards = bool(re.search(r"\b(standards?|codes?)\b", q)) and bool(standards)
    if not RE_STANDARD_Q.search(q) and len(standards) < len(mats):
        # a design, welding or coating standard is not a grade: listed only when the question asks for standards
        mats = [m for m in mats if m.attrs.get("role") != "standard"]
    elif asks_standards:
        mats = standards
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        on_sheet = [m for m in mats if m.sheet == named_sheet]
        if not on_sheet:
            return None  # this sheet has no material facts of its own; let text-search look at its notes
        mats = on_sheet
    comp = [m for m in mats if any(t.rstrip("s") in m.attrs.get("component", "").lower() for t in toks if len(t) > 3)]
    if size_hit and not grade_hit and not any(m.attrs.get("size") for m in comp):
        # A bare size/diameter question only belongs here when a component-matched material fact
        # actually carries a size (e.g. "bolt size") -- otherwise this is a dimension-style question
        # (e.g. "base plate size", "anchor rod diameter") that another rule already answers.
        return None
    if len(comp) == 1:
        # A single component match can still be wrong: a compound component name in the question
        # ("anchor washer") can hit on one word ("anchor") while its other word ("washer") matches no
        # material at all -- decline rather than answer with the wrong component, same as
        # rule_component_spec declining on a low-confidence match. Checked against this *exact*-match
        # `comp` only, before the synonym extension below -- a synonym match (e.g. "plates" ->
        # "Connections") deliberately has no literal-substring overlap with the question by design,
        # so judging it with this same literal check would always (wrongly) decline it.
        # Reuses the same property-word set rule_component_spec excludes from its own
        # component-name matching (COMPONENT_PROPERTY_TOKENS, defined below) rather than a
        # separate hand-rolled list -- this guard's original list missed "length"/"long"/
        # "thick"/"dia" entirely, wrongly declining multi-property questions like "Anchor rod
        # diameter, length, grade?" where "length" isn't a component-name word either.
        # strength/yield/tensile/... name the property being asked, not the component ("yield strength of the
        # W shapes" was declined because "strength" matched no material component).
        trigger_words = COMPONENT_PROPERTY_TOKENS | {
            "steel",
            "strength",
            "strengths",
            "yield",
            "tensile",
            "stress",
            "minimum",
            "specified",
            "specification",
            "required",
        }
        candidate_toks = [t for t in toks if len(t) > 3 and t not in trigger_words]
        all_components = " ".join(m.attrs.get("component", "").lower() for m in mats)
        if any(t.rstrip("s") not in all_components for t in candidate_toks):
            return None
    unmatched = [
        t for t in toks if len(t) > 3 and not any(t.rstrip("s") in m.attrs.get("component", "").lower() for m in mats)
    ]
    syn_terms = {s for t in unmatched for s in MATERIAL_COMPONENT_SYNONYMS.get(t.rstrip("s"), ())}
    if syn_terms:
        comp += [m for m in mats if m not in comp and any(s in m.attrs.get("component", "").lower() for s in syn_terms)]
    # No component matched: a *generic* materials question ("what materials are specified?", "what steel grades?")
    # lists everything, but a question naming something else ("glulam beam size and grade", "rebar grade") must not
    # get the whole list at 0.85 -- unless its content words occur in some fact's spec text (e.g. "CSA G40.21").
    if not comp and not asks_standards:
        # a sheet token ("S50-02") scopes, it is not a subject
        content = [
            t
            for t in toks
            if len(t) > 3
            and t not in COMPONENT_PROPERTY_TOKENS
            and t not in GENERIC_MATERIAL_WORDS
            and not RE_SHEETISH_TOK.match(t)
        ]
        if content:
            hay = " ".join(f"{m.attrs.get('spec', '')} {m.value}".lower() for m in mats)
            if not any(t.rstrip("s") in hay for t in content):
                return None
    sel = comp or mats
    # Identical rows (the same component/spec/size/Fy repeated on every sheet or in several callouts) are listed
    # once with all their sheets -- some sets print the same line 8-14 times.
    grouped: dict[tuple, list] = {}
    for m in sel:
        key = (
            m.attrs.get("component") or "Material",
            m.attrs.get("size") or "",
            m.attrs.get("spec") or m.value,
            str(m.attrs.get("fy_all_mpa") or m.attrs.get("fy_mpa") or ""),
            str(m.attrs.get("fy_max_mpa") or ""),
        )
        grouped.setdefault(key, []).append(m)
    rows = []
    for (component, size, spec, fy, fy_max), ms in grouped.items():
        sheets = sorted({m.sheet for m in ms}, key=sheet_sort_key)
        times = f" (×{len(ms)})" if len(ms) > len(sheets) else ""
        rows.append(
            f"- {component}: "
            + (f"{size} " if size else "")
            + f"{spec}"
            + (f", Fy={fy} MPa" if fy else "")
            + (f" (Fymax={fy_max} MPa)" if fy_max else "")
            + (" (several yield values in one note)" if "/" in fy else "")
            + f" — {', '.join(sheets)}{times}"
        )
    return Answer(
        "Materials from the general notes:\n" + "\n".join(rows),
        [m.id for m in sel],
        0.9 if comp else 0.85,
        "rule:materials",
    )


# A number-with-mm is only the grout's own thickness when it sits immediately next to the word
# "grout" -- a masonry general-notes paragraph often bundles several unrelated
# grout-related numbers (pour-lift limits, cleanout clearances, minimum joint heights) in the same
# note as an actual grout mention ("GROUT IN LIFTS NOT EXCEEDING 1200 mm", "CLEANOUTS FOR
# POURS OVER 1500mm"); a number elsewhere in the note is one of those, not a grout thickness. Three
# conventions are covered: "30mm GROUT" (value before), "GROUT: 40mm THICK" (value after) and "25mm
# NON-SHRINK GROUT" (the most common, so the "non-shrink" qualifier may sit between the number and
# "grout"). No "thick" word is required, since the value-before convention has none.
RE_GROUT_THICKNESS = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*mm\s*(?:non[- ]?shrink\s+)?grout\b|\bgrout\s*[:\-]?\s*(?:is\s+)?(\d+(?:\.\d+)?)\s*mm)",
    re.I,
)


def rule_grout(q, toks, idx: Index):
    """Cross-checks grout-thickness mentions across sheets; flags it explicitly when sheets disagree
    instead of just returning the matched text (grout mentions land in both 'note' and 'text' facts)."""
    if not re.search(r"\bgrout\b", q):
        return None
    # This rule only knows grout *thickness*. A question about grout strength / fill / cores / spacing / lifts is not
    # its question, and answering it with a thickness cross-check ("what grout strength?") is wrong.
    if re.search(
        r"\b(strength|mpa|psi|fill|filled|cores?|spacing|lifts?|pour|slump|mix|type|class)\b", q
    ) and not re.search(r"\b(thick|thickness|depth|bed)\b", q):
        return None
    facts = [f for f in idx.by_kind("note", "text") if re.search(r"\bgrout\b", f.source_text, re.I)]
    by_sheet: dict[str, set[str]] = {}
    ids_by_sheet: dict[str, list[str]] = {}
    for f in facts:
        for m in RE_GROUT_THICKNESS.finditer(f.source_text):
            val = m.group(1) or m.group(2)
            by_sheet.setdefault(f.sheet, set()).add(val)
            ids_by_sheet.setdefault(f.sheet, []).append(f.id)
    if not by_sheet:
        return None
    sheets = sorted(by_sheet, key=sheet_sort_key)
    ids = [fid for s in sheets for fid in ids_by_sheet[s]]
    all_values = {v for vs in by_sheet.values() for v in vs}
    rows = [f"- {s}: {', '.join(f'{v}mm' for v in sorted(by_sheet[s], key=float))}" for s in sheets]
    if len(all_values) > 1:
        cite = "; ".join(f"{s} says {', '.join(f'{v}mm' for v in sorted(by_sheet[s], key=float))}" for s in sheets)
        text = f"Sheets disagree on grout thickness — {cite}.\n\nGrout thickness mentions by sheet:\n" + "\n".join(rows)
        conf = 0.9
    else:
        text = "Grout thickness mentions by sheet:\n" + "\n".join(rows)
        conf = 0.85
    return Answer(text, ids, conf, "rule:grout")


PROP_CLASS = {
    "thick": "thick",
    "thickness": "thick",
    "thk": "thick",
    "long": "long",
    "lg": "long",
    "length": "long",
    "dia": "dia",
    "diam": "dia",
    "diameter": "dia",
    "ø": "dia",
}


RE_COMPONENT_SPEC = re.compile(
    r"(\d+(?:-\d+/\d+|/\d+)?(?:\.\d+)?)\s*(mm|\")\s*"
    r"(thick(?:ness)?|thk|long|lg\.?|length|dia\.?|diameter|ø)",
    re.I,
)


# The reverse drafting order -- property word first, then the value ("HOLE DIAMETER: min. 30mm",
# vs. RE_COMPONENT_SPEC's "30mm THICK") -- e.g. "BASE PLATE HOLE
# DIAMETER: min. 30mm". An optional "min."/"max."/"approx." qualifier commonly sits between the
# colon and the value in this convention.
RE_COMPONENT_SPEC_REV = re.compile(
    r"(thick(?:ness)?|thk|long|lg\.?|length|dia\.?|diameter|ø)\s*:?\s*(?:min\.?|max\.?|approx\.?)?\s*"
    r"(\d+(?:-\d+/\d+|/\d+)?(?:\.\d+)?)\s*(mm|\")",
    re.I,
)


# A third convention: no property word at all -- the value+unit is followed directly by a sheet-
# material component name ("38mm STEEL DECK", as in "ROOF DECK: 38mm
# STEEL DECK"), where the number is conventionally understood to be that material's thickness.
# Deliberately narrow (a fixed, short list of sheet-material nouns) rather than any noun, since a
# generic "<N>mm <NOUN>" match would be too easy to mistake for some other dimension (a clearance, a
# lap length, a spacing) that just happens to precede an unrelated word.
RE_COMPONENT_SPEC_IMPLICIT_THICK = re.compile(
    r"(\d+(?:-\d+/\d+|/\d+)?(?:\.\d+)?)\s*(mm|\")\s*"
    r"(?:steel\s+)?(deck|slab|topping|plate|sheet)\b",
    re.I,
)


# Question words that say nothing about *which* component, and words that name the same component differently.
_COMPONENT_SPEC_FILLER = {
    "used",
    "specified",
    "provided",
    "shown",
    "required",
    "given",
    "stated",
    "indicated",
    "species",
}


_COMPONENT_SYNONYMS = {"gusset": ("plate",), "gussets": ("plate",), "plate": ("gusset",), "plates": ("gusset",)}


def rule_component_spec(q, toks, idx: Index):
    """Convention assumed: the number and unit immediately precede the property word in the same text
    run ('25mm THICK', '450mm LONG', '3/4" DIAMETER', '16mmO with a slashed-o symbol'), and the
    component name precedes them ('NAME: ...' or 'NAME SHALL BE ...'). Grout thickness is rule_grout's
    question, not this rule's -- it explicitly declines whenever the question mentions grout."""
    if "grout" in q:
        return None
    toks_set = set(toks)
    asked = set()
    if {"thick", "thk"} & toks_set:
        asked.add("thick")
    if {"long", "length"} & toks_set:
        asked.add("long")
    if {"dia", "diam"} & toks_set:
        asked.add("dia")
    if not asked:
        return None

    named_sheet = named_sheet_in(toks, idx)
    pool = idx.by_kind("note", "text")
    if named_sheet:
        pool = [f for f in pool if f.sheet == named_sheet]

    spans_by_id: dict[str, list[tuple[str, int]]] = {}
    for f in pool:
        spans = [
            (m.group(0).strip(), m.start())
            for m in RE_COMPONENT_SPEC.finditer(f.source_text)
            if PROP_CLASS.get(m.group(3).lower().rstrip(".")) in asked
        ]
        spans += [
            (m.group(0).strip(), m.start())
            for m in RE_COMPONENT_SPEC_REV.finditer(f.source_text)
            if PROP_CLASS.get(m.group(1).lower().rstrip(".")) in asked
        ]
        if "thick" in asked:
            spans += [(m.group(0).strip(), m.start()) for m in RE_COMPONENT_SPEC_IMPLICIT_THICK.finditer(f.source_text)]
        if spans:
            spans_by_id[f.id] = spans
    if not spans_by_id:
        return None

    comp_toks = [
        t
        for t in toks
        if t not in COMPONENT_PROPERTY_TOKENS
        and t not in _COMPONENT_SPEC_FILLER
        and not (named_sheet and sheet_ref_matches(t.upper(), named_sheet))
    ]
    if not comp_toks:
        return None

    facts_by_id = {f.id: f for f in pool}
    coverage: dict[str, int] = {}
    for fid in spans_by_id:
        f = facts_by_id[fid]
        meta = idx.sheet_by_number(f.sheet)
        # The note's own words plus its view and sheet title: a single-subject detail sheet says "gusset plate ...
        # seismic brace connection" in its title and just "20mm Plate" in the note.
        hay = (
            f.source_text
            + " "
            + (f.attrs.get("heading") or "")
            + " "
            + (f.view or "")
            + " "
            + ((meta.title if meta else "") or "")
        )
        words = set(re.findall(r"[a-z0-9][a-z0-9.\-\"']*", hay.lower()))
        coverage[fid] = sum(
            1
            for t in comp_toks
            if word_match(t, words) or any(word_match(syn, words) for syn in _COMPONENT_SYNONYMS.get(t, ()))
        )

    best = max(coverage.values())
    best_cov = best / len(comp_toks)
    if best_cov < 0.5:
        return None

    sel_ids = sorted(
        (fid for fid, c in coverage.items() if c == best), key=lambda fid: sheet_sort_key(facts_by_id[fid].sheet)
    )
    rows = []
    for fid in sel_ids:
        f = facts_by_id[fid]
        loc = f.sheet + (f", {f.view}" if f.view else "")
        values = ", ".join(s for s, _ in spans_by_id[fid])
        # A window ending right at the match, not a fixed [:120] slice from the note's start: some
        # templates bundle several unrelated bullet lines into one source_text with no delimiter
        # between them (an "ANCHORS: 450mm LONG" note that runs straight on into an
        # unrelated base-plate-hole-diameter line), and a slice from the start would show both. Some
        # leading context (typically the component's own name) is kept; nothing after the match is
        # shown, since that is where the unrelated content starts.
        first_pos = spans_by_id[fid][0][1]
        excerpt = f.source_text[max(0, first_pos - 30) : first_pos + len(spans_by_id[fid][0][0])].strip()
        rows.append(f"- {excerpt} → {values} — {loc}")
    conf = 0.85 if best_cov >= 1.0 else 0.75
    return Answer(
        "Component spec found in the note text:\n" + "\n".join(rows),
        sel_ids,
        conf,
        "rule:component-spec",
        caveats=["Value read from the note text; check the highlighted text for the component it describes."],
    )


def rule_concrete(q, toks, idx: Index):
    """ "What is the concrete strength / class / grade?" -- strength is stated either as an f'c / MPa value
    or, on many bridge sets, only as a concrete class ("CONCRETE: CLASS C"). Returns the notes
    that say so, as written; when only classes are given it says that, so a class is never presented as an
    MPa value."""
    if "concrete" not in q or not re.search(
        r"\b(strength|strengths|class|classes|grade|grades|mpa|f'c|fc|specified)\b", q
    ):
        return None
    named_sheet = named_sheet_in(toks, idx)
    notes = [
        f for f in idx.by_kind("note") if re.search(r"\bconcrete\b", f.value, re.I) and f.attrs.get("role") != "heading"
    ]
    if named_sheet:
        notes = [f for f in notes if f.sheet == named_sheet]
    strength = [
        f
        for f in notes
        if re.search(r"\b\d{2}(?:\.\d)?\s?MPa\b|\bf'?c\b", f.value, re.I)
        and re.search(r"\bconcrete\b.{0,80}(?:MPa|f'?c)|(?:MPa|f'?c).{0,80}\bconcrete\b", f.value, re.I)
    ]
    classes = [f for f in notes if re.search(r"\bclass\s+[A-Z]{1,2}\b", f.value, re.I) and f not in strength]
    classes.sort(key=lambda f: not re.search(r"\bshall\b", f.value, re.I))  # full clauses before table-row fragments
    if strength:
        return Answer(
            "Concrete strength as stated:\n" + "\n".join(note_lines(strength)),
            [f.id for f in strength[:6]],
            0.85,
            "rule:concrete",
        )
    if classes:
        a = Answer(
            "No concrete strength in MPa is stated; the notes specify concrete by class:\n"
            + "\n".join(note_lines(classes)),
            [f.id for f in classes[:6]],
            0.8,
            "rule:concrete",
        )
        a.caveats.append(
            "A concrete class is not an MPa value; the class's strength is set in the referenced specification."
        )
        return a
    return None
