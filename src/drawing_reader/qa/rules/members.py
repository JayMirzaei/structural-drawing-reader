"""Rules about members: section labels by role, a named designation, weld symbols."""

from __future__ import annotations

import re

from drawing_reader.qa.answer import Answer, sheet_sort_key
from drawing_reader.qa.text import format_facts, named_sheet_in, named_views_in
from drawing_reader.qa.vocabulary import DIMENSION_TRIGGER_WORDS, MEMBER_WORDS
from drawing_reader.schema import Fact, Index

# A question containing one of these is asking about a *property* of a member/plate (its thickness,
# grade, a hole's diameter, ...), not the member/plate's own designation -- rule_sections only knows
# designations, so it should defer confidence to whichever rule actually answers the property instead
# of confidently dumping every label of that type. One shared pattern, used in both places that need it.
RE_SECTIONS_PROPERTY_HINT = re.compile(
    r"\b(angle|angles|thick|thickness|grade|grades|elevation|elevations|level|levels|weld|welds|"
    r"bolt|bolts|anchor|anchors|grout|force|forces|length|height|spacing|callout|callouts|"
    r"diameter|diameters|dia|hole|holes|"
    # concrete/requirement vocabulary: "what is the concrete strength?" must not be
    # answered with steel W-shape labels just because the question also says "column"/"wall".
    r"strength|strengths|concrete|cover|minimum|maximum|requirement|requirements|required|reinforcement|rebar|mpa|f'c)\b"
)


RE_SECTIONS_CONCRETE_HINT = re.compile(r"\b(concrete|f'c|rebar|reinforced|reinforcement|cover|stirrups?|mpa)\b")


# "Which sheet shows ...?" / "What is the drawing number of ...?" ask for a sheet, not for the member labels
# that happen to contain the topic word ("crane beam end stop", "glulam beam connections").
RE_LOCATOR_Q = re.compile(
    r"^(?:which|what)\s+(?:sheets?|drawings?)\b|\bdrawing\s+numbers?\b|\bwhich\s+sheets?\s+(?:show|has|have|contain|contains|include)\b"
)


def _ambiguous_member_roles(word: str) -> set[str]:
    """`MEMBER_WORDS` only encodes a member's orientation and cross-section shape
    family, not its structural role -- two real, different roles (e.g. "strut" vs "tie", both
    horizontal HSS/W) can map to the exact same (orientation, family) pair, so a query for one
    silently matches labels that are actually the other role too. Returns the other MEMBER_WORDS
    word(s) `word` can't actually be told apart from, so callers can caveat the answer honestly
    instead of presenting a geometry-only guess as if it named the specific role asked about."""
    ori, fams = MEMBER_WORDS[word]
    key = (ori, frozenset(fams))
    stem = word[:-1] if word.endswith("s") and word[:-1] in MEMBER_WORDS else word
    siblings = set()
    for w2, (o2, f2) in MEMBER_WORDS.items():
        if (o2, frozenset(f2)) != key:
            continue
        stem2 = w2[:-1] if w2.endswith("s") and w2[:-1] in MEMBER_WORDS else w2
        if stem2 != stem:
            siblings.add(stem2)
    return siblings


def rule_sections(q, toks, idx: Index):
    labels = idx.by_kind("label")
    if not labels:
        return None
    # `(?!-\w)`: "post-tensioning" / "tie-down" are not the member words "post" / "tie" (a plain `\b` treats the
    # hyphen as a boundary); a hyphen *before* the word ("x-brace", "cross-brace") is still a member.
    hit = [w for w in MEMBER_WORDS if re.search(rf"\b{w}\b(?!-\w)", q)]
    plate = re.search(r"\b(plate|plates|gusset|gussets|pl)\b", q)
    generic = re.search(r"\b(section|sections|member sizes?|members|shapes?|designation|hss|w-?shape)\b", q)
    if not (hit or plate or generic):
        return None
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        labels = [f for f in labels if f.sheet == named_sheet]
    # A view named in the question ("beam at the top of BRACED FRAME 3 (C-D)") restricts the labels to that view's own.
    view_titles = named_views_in(q, idx)
    view_scoped = False
    if view_titles:
        in_views = [f for f in labels if f.view in view_titles]
        if in_views:
            labels, view_scoped = in_views, True
    sel: list[Fact] = []
    if hit:
        for w in hit:
            ori, fams = MEMBER_WORDS[w]
            sel += [f for f in labels if f.attrs.get("orientation") == ori and f.attrs.get("family") in fams]
    detail = re.findall(r"\b(c\d{1,2}|detail\s*\d{1,2}|[a-z]+ tier)\b", q)
    thickness_q = bool(re.search(r"\b(thick|thickness)\b", q))
    if plate:
        pls = [f for f in labels if f.attrs.get("family") == "PL"]
        if detail:
            keys = [d.replace("detail", "").strip().upper() for d in detail]
            in_view = [f for f in pls if any(key in (f.view or "").upper() for key in keys)]
            pls = in_view or pls
        if thickness_q:
            # a bare 'PL t' is a thickness callout; a 'PL AxBxC' label in the same detail (or its
            # side view) is a separately sized plate, not the gusset/connection plate being asked
            # about -- prefer the bare callouts when any exist in the scoped set.
            bare = [f for f in pls if not f.attrs.get("plan")]
            pls = bare or pls
        sel += pls
    if not sel and generic and not (named_sheet and hit):
        # a hit-word (e.g. "column") explicitly named on a sheet that has none should say so, not
        # fall back to every other label on that sheet just because the question also said "sections"
        sel = [f for f in labels if f.attrs.get("family") != "PL"] or labels
    # Orientation is inferred from how the label is *rotated*, which only means something when the label is drawn
    # along the member; detail sheets use horizontal leader-line labels for diagonal braces etc., so a strict
    # orientation filter reports "none found" although the brace is labelled on the sheet. On a named sheet, when the
    # strict orientation filter empties the selection but labels of an allowed family exist, show them -- flagged. A
    # general note that states the size of the asked member ("STAIR STRINGERS: C250X30") governs; labels that merely
    # share the member's orientation ("diagonal" W460x52 beams) are a weaker second tier.
    note_sizes: list[Fact] = []
    if hit and not view_scoped:
        for w in hit:
            for n in idx.by_kind("note"):
                if named_sheet and n.sheet != named_sheet:
                    continue
                m = re.search(
                    rf"\b{w}s?\b[^.;]{{0,60}}?\b(?:consist|made up|comprise|use|using|be|of)\b[^.;]{{0,30}}?\b((?:C|MC|W|HSS|L|WT|S)\d[\dA-Za-z.]*[xX×]\d[\dA-Za-z.xX×]*)",
                    n.source_text,
                    re.I,
                )
                if m:
                    note_sizes.append(n)
    if note_sizes and sel:
        noted = {
            re.sub(r"\s+", "", m.group(1)).upper()
            for n in note_sizes
            for m in re.finditer(r"\b((?:C|MC|W|HSS|L|WT|S)\d[\dA-Za-z.]*[xX×]\d[\dA-Za-z.xX×]*)", n.source_text, re.I)
        }
        first = [f for f in sel if f.attrs.get("section", f.value).upper() in noted]
        if first:
            sel = first
    if view_scoped and not sel:
        return None  # the named view has no label of that kind: do not claim "none in the set" from a scoped list
    loose_note = None
    if not sel and hit and named_sheet:
        fams_allowed = {fam for w in hit for fam in MEMBER_WORDS[w][1]}
        loose = [f for f in labels if f.attrs.get("family") in fams_allowed]
        if loose and len({f.attrs.get("section", f.value).upper() for f in loose}) <= 12:
            sel = loose
            loose_note = (
                f"No label on {named_sheet} is drawn at the usual orientation for a {', '.join(hit)}; showing the "
                "member-type labels on this sheet regardless of orientation (leader-line labels are horizontal)."
            )
    if not sel:
        if named_sheet:
            what = ", ".join(hit) if hit else ("plates" if plate else "sections")
            # (The loose-orientation fallback above already covers "labels of the right family exist but are drawn
            # at another orientation"; what remains here is a genuine "none of that family on this sheet".)
            conf = 0.8
            if RE_SECTIONS_PROPERTY_HINT.search(q):
                conf = 0.6  # the question is about a property, not the designation; let other rules / LLM lead
            return Answer(f"No section labels for {what} found on {named_sheet}.", [], conf, "rule:sections")
        if hit or plate:
            # a specific member/plate word was asked about ("brace", "gusset") and nothing of that
            # orientation+family exists anywhere: say so plainly, rather than list unrelated labels.
            # Kept below rule_text_search's real-hit confidence (0.7+) so a genuine keyword mention
            # of "brace" elsewhere on the sheets (e.g. in a note) still wins over this negative result.
            what = ", ".join(hit) if hit else "plates"
            return Answer(f"No {what} labels found anywhere in the set.", [], 0.65, "rule:sections")
        return Answer(
            "No member label with that orientation was found; here is every section label in the set:\n"
            + format_facts(labels),
            [f.id for f in labels],
            0.6,
            "rule:sections",
        )
    groups: dict[str, list[Fact]] = {}
    for f in sel:
        groups.setdefault(f.attrs.get("section", f.value).upper(), []).append(f)  # "W250X101" == "W250x101"
    thickness_fired = plate and thickness_q
    rows = []
    for _key, fs in groups.items():
        sec = fs[0].attrs.get("section", fs[0].value)  # first-seen spelling (tests pin the spelling as drawn)
        where = ", ".join(
            f"{s}×{n}"
            for s, n in sorted(
                ((sh, sum(1 for x in fs if x.sheet == sh)) for sh in {x.sheet for x in fs}),
                key=lambda t: sheet_sort_key(t[0]),
            )
        )
        views = sorted({x.view for x in fs if x.view})
        thick_suffix = ""
        if thickness_fired and fs[0].attrs.get("thickness"):
            thick_suffix = f" — thickness {fs[0].attrs['thickness']} mm"
            if fs[0].attrs.get("plan"):
                thick_suffix += f", plan {fs[0].attrs['plan']}"
        rows.append(
            f"- {sec} ({fs[0].attrs.get('family_name', '')}, {fs[0].attrs.get('orientation')} labels) — {where}"
            + (f"; views: {'; '.join(views)}" if views else "")
            + thick_suffix
        )
    what = ", ".join(hit) if hit else ("plates" if plate else "sections")
    conf = 0.85 if hit or plate else 0.7
    if RE_SECTIONS_PROPERTY_HINT.search(q):
        conf = 0.6  # the question is about a property, not the designation; let other rules / LLM lead
    if plate and not hit and re.search(r"\b(size|sizes|dimensions?|plan|wide|width)\b", q):
        # "base plate size/plan dimensions" wants the drawn 410x500, not every PL label; let rule_dimensions lead
        conf = 0.6
    if plate and detail and sel and all(f.attrs.get("family") == "PL" for f in sel):
        conf = 0.85  # the answer is the parsed thickness of a bare 'PL t' callout in the named detail
    if loose_note:
        conf = min(conf, 0.75)  # above a title-only text hit (0.7), below a confirmed-orientation answer (0.85)
    if RE_LOCATOR_Q.search(q):
        conf = min(conf, 0.6)
    if RE_SECTIONS_CONCRETE_HINT.search(q):
        conf = min(conf, 0.5)  # a concrete/reinforcement question is not answered by steel member labels
    cav = (
        [
            "Orientation is inferred from how the label is rotated on the sheet; a label placed horizontally next to a column would be missed."
        ]
        if hit
        else []
    )
    if loose_note:
        cav.append(loose_note)
    ambiguous = {sib for w in hit for sib in _ambiguous_member_roles(w)}
    if ambiguous:
        cav.append(
            f"This app can't tell a {'/'.join(sorted(hit))} apart from a {'/'.join(sorted(ambiguous))} by shape alone "
            "(same orientation and cross-section family) — the results below may include either role."
        )
    return Answer(
        f"Section labels for {what}:\n" + "\n".join(rows), [f.id for f in sel], conf, "rule:sections", caveats=cav
    )


def rule_member_lookup(q, toks, idx: Index):
    """A bare member/plate designation ('W310x31', 'HSS127x127x8.0') is specific enough that an
    exact match against label facts should win outright. In rule_text_search a designation is just another
    keyword and scores too low to show (MIN_CONFIDENCE) when it is the only token that matches."""
    labels = idx.by_kind("label")
    if not labels:
        return None
    by_section: dict[str, list[Fact]] = {}
    for f in labels:
        by_section.setdefault(f.attrs.get("section", f.value).upper(), []).append(f)
    hit_sec = next((key for t in toks if (key := t.rstrip(".").upper()) in by_section), None)
    if not hit_sec:
        return None
    fs = by_section[hit_sec]
    # a line of a schedule / MTO table names the member but does not draw one
    listed = [f for f in fs if f.attrs.get("in_table")]
    fs_drawn = [f for f in fs if not f.attrs.get("in_table")]
    by_sheet: dict[str, int] = {}
    for f in fs_drawn or fs:
        by_sheet[f.sheet] = by_sheet.get(f.sheet, 0) + 1
    where = ", ".join(f"{s}×{n}" for s, n in sorted(by_sheet.items(), key=lambda t: sheet_sort_key(t[0])))
    views = sorted({f.view for f in fs_drawn if f.view})
    orientations = sorted({f.attrs.get("orientation") for f in fs_drawn if f.attrs.get("orientation")})
    sec = fs[0].attrs.get("section", fs[0].value)
    if fs_drawn:
        text = f"{sec} ({fs[0].attrs.get('family_name', '')}) — {len(fs_drawn)} label(s) on the drawings: {where}"
        if listed:
            text += f"\nAlso listed {len(listed)} time(s) in schedule tables (not counted as members drawn)."
    else:
        text = f"{sec} ({fs[0].attrs.get('family_name', '')}) — only listed in schedule tables ({len(listed)} line(s)): {where}; no label on a drawing."
    if orientations:
        text += f"\nOrientation: {', '.join(orientations)}"
    if views:
        text += f"\nViews: {'; '.join(views)}"
    return Answer(text, [f.id for f in fs], 0.9, "rule:member-lookup")


RE_WELD = re.compile(r"\b(weld|welds|welded|fillet|fillets)\b")


_WELD_TRIGGER_WORDS = {"weld", "welds", "welded", "fillet", "fillets"}


def rule_weld(q, toks, idx: Index):
    """Fillet-weld triangle symbols (`parse_welds`) are pure geometry -- this reports what
    is drawn (size, which side(s), typical or not) with evidence; it does not resolve which joint each
    symbol points at (a known limit), same limitation as rule_angles/rule_dimensions. Yields when
    the index has no weld facts at all, so a prose "WELD..." note is still found by rule_text_search
    (some drawing sets state weld requirements in a note rather than drafting the triangle symbol)."""
    if not RE_WELD.search(q):
        return None
    welds = idx.by_kind("weld")
    if not welds:
        return None

    named_sheet = named_sheet_in(toks, idx)
    scoped = False
    if named_sheet:
        sheet_welds = [w for w in welds if w.sheet == named_sheet]
        if not sheet_welds:
            return Answer(f"No weld symbols found on {named_sheet}.", [], 0.8, "rule:weld")
        welds, scoped = sheet_welds, True
    else:
        # len(p) >= 2, not > 3: a connection/detail identifier like "C1"/"C2"/"C3" is exactly the
        # kind of thing this view-matching is meant to scope by, and a real 2-char match still has
        # to equal an actual word in that view's own title (_match_count below), which is already a
        # fairly strong signal on its own: "What welds are shown for C1 and C2?" scopes to those views.
        content_toks = [
            p
            for t in toks
            for p in re.split(r"[-.]", t)
            if len(p) >= 2 and p not in DIMENSION_TRIGGER_WORDS and p not in _WELD_TRIGGER_WORDS
        ]
        if content_toks:

            def _match_count(view: str) -> int:
                words = set(re.findall(r"[a-z0-9]+", view.lower()))
                return sum(1 for t in content_toks if t in words)

            counts = {w.id: _match_count(w.view) for w in welds if w.view}
            max_count = max(counts.values(), default=0)
            if max_count > 0:
                welds = [w for w in welds if w.view and counts[w.id] == max_count]
                scoped = True

    sides_label = {"both": "both sides", "arrow": "arrow side", "other": "other side"}
    rows = []
    for w in sorted(welds, key=lambda w: (sheet_sort_key(w.sheet), w.bbox[1])):
        side = sides_label.get(w.attrs.get("sides"), w.attrs.get("sides", ""))
        typ = " (typ.)" if w.attrs.get("typical") else ""
        loc = w.sheet + (f" ({w.view})" if w.view else "")
        rows.append(f"- {w.value} mm fillet, {side}{typ} — {loc}")
    conf = 0.85 if scoped else 0.8
    # Weld sizes also written in prose next to the symbols ("STIFF. PLATE & WELD: B1 & B2 = 8mm / B3 = 10mm",
    # "ALL WELDS 5mm") are reported separately: symbols and notes can differ, and the engineer should see both.
    sheets = {w.sheet for w in welds}
    written, seen_w = [], set()
    pool = [f for f in idx.by_kind("note", "text") if f.sheet in sheets]
    for f in pool:
        txt = f.source_text.strip()
        near_heading = False
        if not re.search(r"\bweld", txt, re.I):
            # a value line printed right under a "...WELD:" heading note (a separate text fact, never joined by the
            # parser)
            near_heading = bool(re.search(r"=\s*\d+(?:\.\d+)?\s*mm", txt, re.I)) and any(
                h.sheet == f.sheet
                and re.search(r"\bweld", h.source_text, re.I)
                and not re.search(r"\d\s*mm", h.source_text)
                and 0 <= f.bbox[1] - h.bbox[3] <= 25
                and abs(f.bbox[0] - h.bbox[0]) <= 60
                for h in pool
            )
            if not near_heading:
                continue
        if not re.search(r"\d\s*mm", txt, re.I) or (f.sheet, txt) in seen_w:
            continue
        seen_w.add((f.sheet, txt))
        written.append(f)
    written = written[:6]
    text = "Weld symbols:\n" + "\n".join(rows)
    ids = [w.id for w in welds]
    if written:
        text += "\nWeld sizes written in notes:\n" + "\n".join(
            f"- “{f.source_text.strip()[:120]}” — {f.sheet}" for f in written
        )
        ids += [f.id for f in written]
    return Answer(
        text,
        ids,
        conf,
        "rule:weld",
        caveats=["Which joint each weld symbol points at is not resolved by rules; check the highlighted location."]
        + (["Weld sizes in notes and the drawn symbols are listed separately; they can differ."] if written else []),
    )
