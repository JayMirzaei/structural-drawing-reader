"""Rules that answer from title-block facts: revisions, scales, project fields and location."""

from __future__ import annotations

import re

from drawing_reader.qa.answer import Answer, sheet_sort_key
from drawing_reader.qa.text import named_sheet_in, named_views_in
from drawing_reader.schema import Fact, Index


def _rev_rank(f: Fact):
    """Revision codes aren't always plain integers — some templates use lettered pre-issue stages
    (A, B, C...) followed by numeric post-issue revisions (0, 1, 2...); a numeric code always
    outranks a lettered one (it's the later, superseding stage), and within each group the higher
    value/letter wins."""
    n = (f.attrs.get("number") or "").strip()
    return (1, int(n)) if n.isdigit() else (0, n)


# A revision number/letter, read from the raw question the way rule_note_lookup (RE_NOTE_NUM) reads
# a note number -- tokens() drops single-digit tokens, so "2" never reaches `toks`. This regex alone
# is not enough to keep the bare word "revisions" from being misread as a code: backtracking lets
# "rev(?:ision)?s?" give up its trailing "s?" so the capture group lands on the literal plural "s" of
# "revisions" itself (which sits right before a real word boundary, e.g. "revisions does") -- so the
# capture is only trusted below when it matches one of this index's actual revision codes.
RE_REV_NUM = re.compile(r"\brev(?:ision)?s?\s*(?:no\.?|#)?\s*([0-9]{1,2}|[A-Za-z])\b")


def rule_revisions(q, toks, idx: Index):
    if not re.search(r"\b(revision|revisions|rev\b|issued|issue date|latest issue|last issued)", q):
        return None
    all_revs = idx.by_kind("revision")

    # (a) a sheet-shaped token was named but it isn't in this set -- decline entirely rather than
    # falling back to the unscoped dump (rule_views:483 / rule_note_lookup:602 pattern).
    named_sheet = named_sheet_in(toks, idx)
    if not named_sheet and any(re.fullmatch(r"[a-z]{1,2}[.\-]?\d+([.\-]\d+)?[a-z]?", t) for t in toks):
        return None

    known_numbers = {(f.attrs.get("number") or "").lower() for f in all_revs}
    m = RE_REV_NUM.search(q)
    raw_rev = m.group(1) if m else None
    rev_number = raw_rev if raw_rev and raw_rev.lower() in known_numbers else None

    # A *numeric* revision was named but doesn't exist anywhere in this set -- say so explicitly
    # rather than fall through to "latest revision", which answers a different question. Digits only:
    # a bare letter here is usually the "revisions" plural that this regex also matches (see its
    # docstring), so an unmatched letter code falls through to the latest-revision answer.
    if raw_rev is not None and rev_number is None and raw_rev.isdigit():
        where = f" on {named_sheet}" if named_sheet else ""
        return Answer(f"No revision {raw_rev} found{where}.", [], 0.8, "rule:revisions")

    if not named_sheet and rev_number is None:
        # Unscoped: the latest revision of every sheet. A set with no sheets has nothing to list.
        if not idx.sheets:
            return None
        rows, ids = [], []
        for s in idx.sheets:
            revs = [f for f in all_revs if f.sheet == s.number]
            if not revs:
                rows.append(f"- {s.number}: no revision rows found")
                continue
            latest = max(revs, key=_rev_rank)
            rows.append(
                f"- {s.number}: latest is rev {latest.attrs.get('number')} “{latest.attrs.get('description')}” {latest.attrs.get('date')} ({len(revs)} rows)"
            )
            ids.append(latest.id)
            if re.search(r"\b(all|every|history|table)\b", q):
                ids += [f.id for f in revs]
        return Answer("Revision status per sheet:\n" + "\n".join(rows), ids, 0.9, "rule:revisions")

    # (b) restrict to the named sheet's revision facts.
    scope = [f for f in all_revs if not named_sheet or f.sheet == named_sheet]

    # (c) restrict to the named revision number/letter, if any.
    if rev_number is not None:
        sheet_scope = scope
        scope = [f for f in scope if (f.attrs.get("number") or "").lower() == rev_number.lower()]
        if not scope and named_sheet:
            found_nums = {f.attrs.get("number") or "" for f in sheet_scope}
            found = ", ".join(sorted(found_nums, key=lambda n: (1, int(n)) if n.isdigit() else (0, n)))
            return Answer(
                f"No revision {rev_number} found on {named_sheet} (rows found: {found}).", [], 0.8, "rule:revisions"
            )

    if not scope:
        where = f" on {named_sheet}" if named_sheet else ""
        return Answer(f"No revision rows found{where}.", [], 0.8, "rule:revisions")

    # (d) a count, not a listing.
    if re.search(r"\bhow many\b", q):
        where = f" on {named_sheet}" if named_sheet else ""
        return Answer(f"{len(scope)} revision(s){where}.", [f.id for f in scope], 0.9, "rule:revisions")

    # (e) every matching row, not just the latest.
    if re.search(r"\b(all|every|history|table)\b", q):
        lines = [
            f"- {f.sheet}: rev {f.attrs.get('number')} “{f.attrs.get('description')}” {f.attrs.get('date')}"
            for f in sorted(scope, key=lambda f: (sheet_sort_key(f.sheet), _rev_rank(f)))
        ]
        header = f"Revision history for {named_sheet}:" if named_sheet else "Revision history:"
        return Answer(header + "\n" + "\n".join(lines), [f.id for f in scope], 0.9, "rule:revisions")

    if named_sheet and rev_number is None:
        latest = max(scope, key=_rev_rank)
        text = f"{named_sheet}: latest is rev {latest.attrs.get('number')} “{latest.attrs.get('description')}” {latest.attrs.get('date')} ({len(scope)} rows)"
        return Answer(text, [latest.id], 0.9, "rule:revisions")

    lines = [
        f"- {f.sheet}: rev {f.attrs.get('number')} “{f.attrs.get('description')}” {f.attrs.get('date')}"
        for f in sorted(scope, key=lambda f: sheet_sort_key(f.sheet))
    ]
    header = f"Revision {rev_number} on {named_sheet}:" if named_sheet else f"Revision {rev_number}:"
    return Answer(header + "\n" + "\n".join(lines), [f.id for f in scope], 0.9, "rule:revisions")


RE_TITLED_SCALE = re.compile(r"^1\s?:\s?(\d{1,4})$", re.I)


def _scale_note(v: Fact) -> str:
    """A dimension-consensus cross-check for a view's titled scale (assign_scale_consensus in
    the parser sets scale_measured/scale_support). Not a re-derivation -- just a note appended to
    the view row rule_scale already renders."""
    measured, support = v.attrs.get("scale_measured"), v.attrs.get("scale_support")
    if not measured or not support:
        return ""
    k, n = (int(x) for x in support.split("/"))
    best = float(measured.split(":")[1].strip())
    m = RE_TITLED_SCALE.match((v.attrs.get("scale") or "").strip())
    if m:
        titled = float(m.group(1))
        if abs(best - titled) <= 0.10 * titled:
            return f" — dimension strings agree ({k}/{n})"
        red = v.attrs.get("print_reduction")
        if red and abs(best / titled - red) <= 0.15 * red:
            return f" — dimension strings agree ({k}/{n}) once the sheet's ~{red}x print reduction is allowed for"
        if k >= 4 and k / n >= 0.6 and abs(best - titled) > 0.25 * titled:
            return f" — check: dimension strings measure ~{measured} ({k}/{n}), not the titled 1 : {int(titled)}"
        return ""
    if k >= 3 and k / n >= 0.5:
        return f" — measured ~{measured} from dimension strings ({k}/{n})"
    return ""


def rule_scale(q, toks, idx: Index):
    if "scale" not in q:
        return None
    named_sheet = named_sheet_in(toks, idx)
    if named_sheet:
        meta = idx.sheet_by_number(named_sheet)
        sheet_views = [v for v in idx.by_kind("view") if v.sheet == named_sheet]
        rows = [f"- {meta.number} ({meta.title}): sheet scale {meta.scale or 'n/a'}"] if meta else []
        vrows = [
            f"  - {v.sheet} view {v.attrs.get('number', '')} {v.attrs['title']}: {v.attrs['scale']}{_scale_note(v)}"
            for v in sheet_views
        ]
        ids = [
            f.id for f in idx.by_kind("titleblock") if f.attrs.get("field") == "Scale" and f.sheet == named_sheet
        ] + [v.id for v in sheet_views]
        return Answer(
            "Scales:\n" + "\n".join(rows) + ("\nViews:\n" + "\n".join(vrows) if vrows else ""), ids, 0.85, "rule:scale"
        )
    views = idx.by_kind("view")
    # `all`, not `any`: matching on a single shared word between two otherwise-unrelated titles
    # ("1 FOUNDATION PLAN" and an unrelated "SLEEVE AT FOUNDATION WALL" detail, both
    # containing "foundation") dragged the second one into a scale answer about the first.
    scale_toks = [t for t in toks if len(t) > 3 and t not in ("scale", "view", "views")]
    named_titles = named_views_in(q, idx)
    named = [v for v in views if v.attrs.get("title") in named_titles] or [
        v for v in views if scale_toks and all(t in (v.attrs.get("title") or "").lower() for t in scale_toks)
    ]
    if named:
        return Answer(
            "\n".join(f"- {v.attrs['title']} on {v.sheet}: {v.attrs['scale']}{_scale_note(v)}" for v in named),
            [v.id for v in named],
            0.85,
            "rule:scale",
        )
    rows = [f"- {s.number} ({s.title}): sheet scale {s.scale or 'n/a'}" for s in idx.sheets]
    vrows = [
        f"  - {v.sheet} view {v.attrs.get('number', '')} {v.attrs['title']}: {v.attrs['scale']}{_scale_note(v)}"
        for v in views
    ]
    if not rows and not vrows:
        return None  # no sheet scale and no view scale: an empty list is no answer
    ids = [f.id for f in idx.by_kind("titleblock") if f.attrs.get("field") == "Scale"] + [v.id for v in views]
    return Answer(
        "Scales:\n" + "\n".join(rows) + ("\nViews:\n" + "\n".join(vrows) if vrows else ""), ids, 0.85, "rule:scale"
    )


RE_PROJECT_TRIGGER = re.compile(
    r"\b(project|title ?block|drawn by|checked by|who drew|client|job|date of|dated|"
    r"drew|drawn|checked|date on|when was .*(?:drawn|dated)|project (?:number|no)|job (?:number|no))\b"
)


# (canonical field name, the attrs["field"] values it covers, the question wording that names it) --
# order is priority when a question's wording could match more than one (e.g. "when was ... drawn").
FIELD_DETECT = [
    ("Drawn By", ("Drawn By", "Drawn"), re.compile(r"\b(drew|drawn)\b")),
    ("Checked By", ("Checked By", "Checked"), re.compile(r"\bchecked\b")),
    ("Date", ("Date",), re.compile(r"\b(date|dated|when)\b")),
    (
        "Project Number",
        ("Project Number", "Project No", "Job No", "Job Number"),
        re.compile(r"\b(project|job)\s*(number|no)\b"),
    ),
    ("Client", ("Client",), re.compile(r"\bclient\b")),
]


def _project_field(q: str):
    for name, aliases, pat in FIELD_DETECT:
        if pat.search(q):
            return name, aliases
    return None


RE_LOCATION_Q = re.compile(
    r"\b(?:where\s+is\s+(?:the|this)\s+(?:project|site|job)|(?:project|site|job)\s+(?:location|address)|"
    r"(?:location|address)\s+of\s+(?:the|this)\s+(?:project|site|job)|what\s+(?:city|town)|which\s+(?:city|town))\b"
    r"|^\W*(?:what|where)(?:'s|\s+is)\s+the\s+(?:location|address)\W*$"  # the bare forms: "What is the address?"
)


def rule_location(q, toks, idx: Index):
    """ "Where is the project?" -- the location text read from the sheets (labelled field, street address, city and
    province, or legal land description), with the other places that appear. The set may also print the designer's own
    office address, so the answer shows what it was read from and says to check it."""
    if not RE_LOCATION_Q.search(q):
        return None
    best = idx.project.get("Location", "")
    facts = [f for f in idx.by_kind("titleblock") if f.attrs.get("field") == "Location"]
    if not best or not facts:
        return Answer(
            "No project location (address, city or legal land description) could be read from the sheets.",
            [],
            0.5,
            "rule:location",
        )

    def norm(v):
        return re.sub(r"[^A-Z0-9]", "", v.upper())

    main = [f for f in facts if norm(f.value) == norm(best)]
    others: dict[str, set[str]] = {}
    for f in facts:
        if norm(f.value) != norm(best):
            others.setdefault(f.value, set()).add(f.sheet)
    sheets = sorted({f.sheet for f in main}, key=sheet_sort_key)
    text = f"{best} (read from {len(sheets)} sheet(s): {', '.join(sheets[:6])}{'...' if len(sheets) > 6 else ''})."
    if others:
        extra = sorted(others.items(), key=lambda kv: -len(kv[1]))[:3]
        text += "\nAlso on the sheets: " + "; ".join(f"{v} ({len(sh)} sheet(s))" for v, sh in extra) + "."
    text += (
        "\nThis can be the designer's or client's office address rather than the site -- check it against the sheet."
    )
    conf = min(0.8, max(f.confidence for f in main))
    return Answer(text, [f.id for f in main][:6], conf, "rule:location")


def rule_project(q, toks, idx: Index):
    if not RE_PROJECT_TRIGGER.search(q) or RE_LOCATION_Q.search(q):
        return None  # a "where is the project" question belongs to rule_location
    if re.search(r"\b(revision|revisions|rev|issued|issue)\b", q):
        return None  # those belong to rule_revisions
    field = _project_field(q)
    named_sheet = named_sheet_in(toks, idx)

    if named_sheet:
        sheet_facts = [
            f for f in idx.by_kind("titleblock") if f.sheet == named_sheet and f.attrs.get("field") != "sheet_title"
        ]
        if field:
            fname, aliases = field
            sheet_facts = [f for f in sheet_facts if f.attrs.get("field") in aliases]
            if not sheet_facts:
                return Answer(f"No {fname} found in the title block of {named_sheet}.", [], 0.8, "rule:project")
        rows, ids, seen = [], [], set()
        for f in sheet_facts:
            key = (f.attrs.get("field"), f.value)
            if key in seen:
                continue
            seen.add(key)
            rows.append(f"- {f.attrs.get('field')}: {f.value}")
            ids.append(f.id)
        if not rows:
            return None
        return Answer(f"Title block for {named_sheet}:\n" + "\n".join(rows), ids, 0.9, "rule:project")

    if field:
        fname, aliases = field
        facts = [f for f in idx.by_kind("titleblock") if f.attrs.get("field") in aliases]
        if facts:
            groups: dict[str, list[Fact]] = {}
            for f in facts:
                groups.setdefault(f.value, []).append(f)
            ordered = sorted(
                groups.items(), key=lambda kv: sheet_sort_key(sorted({f.sheet for f in kv[1]}, key=sheet_sort_key)[0])
            )
            rows, ids = [], []
            for value, fs in ordered:
                sheets = sorted({f.sheet for f in fs}, key=sheet_sort_key)
                rows.append(f"- {fname}: {value} — {', '.join(sheets)}")
                ids += [f.id for f in fs]
            return Answer("\n".join(rows), ids, 0.85, "rule:project")
        # A specific field was asked ("who is the client?") and no title block carries it: say that, at a confidence
        # that lets keyword search lead, instead of falling through to the generic dump of whatever *other* fields
        # exist ("Who is the client?" must not be answered with the project number). 0.5 is below MIN_CONFIDENCE: some
        # title blocks (right-strip layouts) are not read at all, so this must not be shown as "absent" -- it only
        # stops the generic dump below from answering a different field.
        return Answer(f"No {fname} field could be read from the title blocks of this set.", [], 0.5, "rule:project")

    # A dash (or similar filler) value means the field is a blank/unfilled placeholder on this
    # template, not real data -- reporting it at 0.85 confidence looked exactly as
    # confident as a genuinely-found value. Drop it from what's shown, and decline entirely (rather
    # than a confident-looking answer with nothing useful in it) if nothing real is left.
    rows, ids = [], []
    for k, v in idx.project.items():
        if not v.strip(" -—–"):
            continue
        rows.append(f"- {k}: {v}")
        # Cite the specific fact(s) behind *this* row, not an unrelated grab-bag from every field on
        # every sheet -- "name" is special (built from repeated large title-block text, not a plain
        # field/value pair) so its evidence is the matching sheet-title facts instead.
        if k == "name":
            ids += [
                f.id
                for f in idx.by_kind("titleblock")
                if f.attrs.get("field") == "sheet_title" and f.value in v.split(" / ")
            ][:3]
        else:
            ids += [f.id for f in idx.by_kind("titleblock") if f.attrs.get("field") == k and f.value == v][:3]
    if not rows:
        return None
    return Answer("Title block (common to the set):\n" + "\n".join(rows), ids[:12], 0.85, "rule:project")
