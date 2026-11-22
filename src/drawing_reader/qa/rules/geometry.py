"""Rules about drawn geometry: angles, elevation markers, grid bubbles and dimension strings."""

from __future__ import annotations

import re

from drawing_reader.qa.answer import Answer
from drawing_reader.qa.text import named_sheet_in
from drawing_reader.qa.vocabulary import DIMENSION_TRIGGER_WORDS, GENERIC_DIM_WORDS, MEMBER_WORDS
from drawing_reader.schema import Fact, Index


def rule_angles(q, toks, idx: Index):
    if not re.search(r"\b(angle|angles|inclination|slope|degrees?)\b", q):
        return None
    ang = idx.by_kind("angle")
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        ang = [a for a in ang if a.sheet == named_sheet]
        if not ang:
            return Answer(f"No angle annotations found on {named_sheet}.", [], 0.8, "rule:angles")
    elif not ang:
        return Answer("No angle annotations (values with a ° sign) were found on the sheets.", [], 0.6, "rule:angles")
    rows = [f"- {a.value}° — {a.sheet}" + (f" ({a.view})" if a.view else "") for a in ang]
    return Answer(
        "Angle annotations:\n" + "\n".join(rows),
        [a.id for a in ang],
        0.88,
        "rule:angles",
        caveats=["Which member each angle belongs to is not resolved by rules; check the highlighted location."],
    )


def rule_elevations(q, toks, idx: Index):
    els = idx.by_kind("elevation")
    named_sheet = named_sheet_in(toks, idx)
    # "Level 2"/"roof beam" alone is not an elevation question when the question is really about something *on* that
    # level ("what deck is used at Level 2?", "slab thickness on the Level 1 plan") -- those were once answered with
    # "Elevation markers: -: 6 mm". Unambiguous elevation words always ask; the weak ones only when no other
    # property is being asked about.
    strong_ask = re.search(r"\b(elevation|elevations|el\.|datum|tof|bof|top of|bottom of)\b", q)
    weak_ask = re.search(r"\b(level|levels|roof beam|loading beam)\b", q)
    other_prop = re.search(
        r"\b(thick|thickness|size|sizes|grade|grades|weld|welds|bolt|bolts|plate|plates|deck|slab|rebar|spacing|"
        r"diameter|length|strength|material|materials|section|sections|column|columns|beam|beams)\b",
        q,
    )
    ask = strong_ask or (weak_ask and not other_prop)
    # Whole-word match of the marker name, so a one-character name ("-") does not match every hyphenated question
    # ("BP-C", "C2-04A", "BF 5 (D-E)").
    exact = [
        e
        for e in els
        if e.attrs.get("name", "") and re.search(rf"(?<![a-z0-9-]){re.escape(e.attrs['name'].lower())}(?![a-z0-9-])", q)
    ]
    loose = [e for e in els if any(t in e.attrs.get("name", "").lower() for t in toks if len(t) > 3)]
    if ask:
        exact_ids = {e.id for e in exact}
        named = exact + [e for e in loose if e.id not in exact_ids]
    else:
        named = exact
    if not ask and not exact:
        return None
    if other_prop and not strong_ask:
        return None  # asks about something else on that level/marker ("deck on Level 2"), not for the elevation value
    sel = named or els
    if not sel:
        return None
    if named_sheet:
        sel = [e for e in sel if e.sheet == named_sheet]
        if not sel:
            return Answer(f"No elevation markers found on {named_sheet}.", [], 0.8, "rule:elevations")
    seen, rows, ids = set(), [], []
    for e in sorted(sel, key=lambda e: float(e.value)):
        key = (e.attrs.get("name"), e.value)
        if key in seen:
            continue
        seen.add(key)
        where = ", ".join(sorted({x.sheet for x in sel if (x.attrs.get("name"), x.value) == key}))
        rows.append(f"- {e.attrs.get('name')}: {e.value} mm — {where}")
        ids += [x.id for x in sel if (x.attrs.get("name"), x.value) == key]
    return Answer(
        "Elevation markers:\n" + "\n".join(rows),
        ids,
        0.85 if (exact and ask) else (0.8 if ask else 0.65),
        "rule:elevations",
    )


def rule_grids(q, toks, idx: Index):
    if not re.search(r"\b(grid|grids|gridline|grid line|axes|axis)\b", q):
        return None
    g = idx.by_kind("grid")
    if not g:
        return None
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        g = [x for x in g if x.sheet == named_sheet]
        if not g:
            return Answer(f"No grid bubbles found on {named_sheet}.", [], 0.8, "rule:grids")
    names = sorted({x.attrs.get("name") for x in g})
    return Answer(
        f"Grid bubbles found: {', '.join(names)}.\n"
        + "\n".join(f"- {n}: on " + ", ".join(sorted({x.sheet for x in g if x.attrs.get("name") == n})) for n in names),
        [x.id for x in g],
        0.85,
        "rule:grids",
    )


RE_DIM_VERTICAL = re.compile(r"\b(heights?|tall|high|rise|vertical)\b")


RE_DIM_HORIZONTAL = re.compile(r"\b(widths?|wide|spacing|bays?|span|horizontal)\b")


RE_DIM_ANY = re.compile(r"\b(dimensions?|lengths?|long)\b|\bhow (far|big)\b")


RE_DIM_SIZE = re.compile(r"\b(size|sizes)\b")


# "member/section" words mean the question wants a designation (rule_sections' job), not a drawn
# value -- even when it also says "size" ("What are the member sizes?"). Same for a MEMBER_WORDS key
# ("Column size?") -- those stay rule_sections' plain designation lookups.
RE_DESIGNATION_WORDS = re.compile(r"\b(member|members|section|sections)\b")


def _numeric_value(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        return 0.0


def rule_dimensions(q, toks, idx: Index):
    """A dimension string's text rotation gives its orientation (see `run_orientation` in `parse.layout`); this
    rule lists what is drawn at that orientation and does not resolve which member a dimension belongs
    to (a known limit) -- no attachment, no arithmetic (e.g. summing tiers), just the drawn values
    with evidence."""
    dims_all = idx.by_kind("dimension")
    if not dims_all:
        return None
    if re.search(r"\belevations?\b", q) and not re.search(r"\bdimensions?\b", q):
        # "elevation of the high roof deck" is rule_elevations' question; "high" must not summon a dimension dump
        return None
    via_size_only = False
    if RE_DIM_VERTICAL.search(q):
        orientation, header = "vertical", "Vertical dimension strings:"
    elif RE_DIM_HORIZONTAL.search(q):
        orientation, header = "horizontal", "Horizontal dimension strings:"
    elif RE_DIM_ANY.search(q):
        orientation, header = None, "Dimension strings:"
    elif RE_DIM_SIZE.search(q) and not any(w in toks for w in MEMBER_WORDS) and not RE_DESIGNATION_WORDS.search(q):
        orientation, header = None, "Dimension strings:"
        via_size_only = True  # "size" alone is a weak cue: a negative here must not be stated confidently
    else:
        return None
    dims = [d for d in dims_all if orientation is None or d.attrs.get("orientation") == orientation]
    if not dims:
        return None

    scoped = False
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        sheet_dims = [d for d in dims if d.sheet == named_sheet]
        if not sheet_dims:
            # Only an explicit "dimension(s)" in the question makes this negative a confident one; "high bay",
            # "wide", "size", "span" are orientation/size cues that appear in questions about anything else.
            explicit = re.search(r"\bdimensions?\b", q)
            return Answer(
                f"No dimension strings found on {named_sheet}.",
                [],
                0.5 if (via_size_only or not explicit) else 0.8,
                "rule:dimensions",
            )
        dims, scoped = sheet_dims, True
    else:
        content_toks = [t for t in toks if len(t) > 3 and t not in DIMENSION_TRIGGER_WORDS]
        if content_toks:
            # rank by how many content words each view's own words contain, not just "any match" --
            # otherwise a generic view like "CAP PLATE - PLAN VIEW" (which shares a word with almost
            # any plan/size question) crowds out the one view that actually matches every word asked
            # (e.g. "base plate" naming "BASE PLATE DETAIL" over "SPLICE PLATE ..." or "CAP PLATE ...").
            def _match_count(view: str) -> int:
                words = set(re.findall(r"[a-z0-9]+", view.lower()))
                return sum(1 for t in content_toks if t in words)

            counts = {d.id: _match_count(d.view) for d in dims if d.view}
            max_count = max(counts.values(), default=0)
            if max_count > 0:
                dims = [d for d in dims if d.view and counts[d.id] == max_count]
                scoped = True
            elif any(t not in GENERIC_DIM_WORDS for t in content_toks):
                # The question names a subject ("crane capacity", "tie size", "bearing") that matches no drawn view:
                # a global dump of the largest dimension strings is not an answer -- decline.
                return None

    groups: dict[tuple[str, str | None], list[Fact]] = {}
    for d in dims:
        groups.setdefault((d.sheet, d.view), []).append(d)
    items = []
    for key, facts in groups.items():
        values = sorted({f.value for f in facts}, key=lambda v: -_numeric_value(v))
        items.append((_numeric_value(values[0]), key, facts, values))
    items.sort(key=lambda t: -t[0])
    shown = items[:8]
    truncated = len(items) - len(shown)

    rows, ids = [], []
    for _, (sheet, view), facts, values in shown:
        loc = sheet + (f" ({view})" if view else "")
        unit = {f.unit for f in facts if re.fullmatch(r"[\d.]+", f.value)}
        # a unit goes on bare numbers only ("3'-6\"" already says feet-inches)
        suffix = f" {unit.pop()}" if len(unit) == 1 else (" mm" if unit else "")
        rows.append(
            f"- {loc}: {', '.join(values)}{suffix}"
            if not (unit and any(not re.fullmatch(r"[\d.]+", v) for v in values))
            else f"- {loc}: "
            + ", ".join(
                v + (f" {next(iter(unit)) if len(unit) == 1 else 'mm'}" if re.fullmatch(r"[\d.]+", v) else "")
                for v in values
            )
        )
        ids += [f.id for f in facts]
    if truncated > 0:
        rows.append(f"- … {truncated} more sheet/view groups; name a sheet or view to narrow.")

    conf = 0.85 if scoped else (0.8 if orientation is not None else 0.7)
    return Answer(
        header + "\n" + "\n".join(rows),
        ids,
        conf,
        "rule:dimensions",
        caveats=["Which member each dimension belongs to is not resolved by rules; check the highlighted location."],
    )
