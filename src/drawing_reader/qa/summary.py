"""What the reader found in a set, in a few lines, and advice when a set is outside its scope."""

from __future__ import annotations

import re
from collections import Counter

from drawing_reader import ocr
from drawing_reader.ingest import render_dpi_for
from drawing_reader.qa.answer import sheet_sort_key
from drawing_reader.schema import Index


def source_kind(idx: Index) -> str:
    """How the text of the set was obtained, in a few words."""
    if idx.is_vector:
        return "vector PDF (text and geometry extracted directly)"
    if idx.from_ocr:
        return "scanned PDF (text read by OCR, so spelling and numbers are approximate)"
    if ocr.available():
        return "PDF with little or no text, and no page that looks scanned for OCR to read: expect little"
    return "PDF with little or no text layer; OCR is not installed, so scanned pages cannot be read: expect little"


def text_layer_notice(idx: Index) -> str | None:
    """A warning for a set with almost no text, which says whether installing OCR would help; None otherwise."""
    if idx.is_vector or idx.from_ocr:
        return None
    if ocr.available():
        return (
            "This PDF has very little text, and none of its pages looks like a scan for OCR to read (a blank page, "
            "or a drawing with very few words). Rules find little; answers will be poor."
        )
    return (
        "This PDF has very little text. If it is a scan, install the OCR extra (`uv sync --extra ocr`) so its "
        "text can be read from the image; until then rules find almost nothing."
    )


def first_look(idx: Index) -> str:
    """A short Markdown summary of what was read: sheets, member sizes, materials, missing references.

    Each section is its own paragraph or list, so it renders as separate blocks."""
    lines = [
        f"**{idx.project.get('name', idx.source.split('/')[-1])}** — {len(idx.sheets)} sheet(s), {source_kind(idx)}"
    ]
    for k in ("Project Number", "Date", "Drawn By", "Checked By"):
        if k in idx.project:
            lines.append(f"- {k}: {idx.project[k]}")
    lines.append("")
    lines.append("**Sheets**")
    for s in idx.sheets:
        views = [v.attrs["title"] for v in idx.by_kind("view") if v.sheet == s.number]
        lines.append(
            f"- {s.number} — {s.title or '?'}"
            + (f" (scale {s.scale})" if s.scale else "")
            + (f": {'; '.join(views)}" if views else "")
        )
    labels = idx.by_kind("label")
    if labels:
        secs = sorted({f.attrs.get("section", f.value) for f in labels})
        lines.append("")
        lines.append(f"**Member / plate designations found ({len(labels)} labels):** " + ", ".join(secs))
    mats = [m for m in idx.by_kind("material") if m.attrs.get("role") != "standard"]
    if mats:
        mat_lines = dict.fromkeys(
            (f"{m.attrs.get('component')}: " if m.attrs.get("component") else "")
            + f"{m.attrs.get('spec') or m.value[:40]}"
            + (f" Fy={m.attrs.get('fy_mpa')} MPa" if m.attrs.get("fy_mpa") else "")
            for m in mats
        )
        lines.append("")
        lines.append("**Materials:** " + "; ".join(mat_lines))
    standards = sorted({m.attrs["spec"] for m in idx.by_kind("material") if m.attrs.get("role") == "standard"})
    if standards:
        lines.append("")
        lines.append("**Standards cited:** " + ", ".join(standards))
    miss = sorted(
        {
            f.attrs["target_sheet"]
            for f in idx.by_kind("reference", "callout")
            if not f.attrs.get("target_in_set", True)
        },
        key=sheet_sort_key,
    )
    if miss:
        lines.append("")
        lines.append(f"**Referenced but not in the set:** {', '.join(miss)}")
    counts = {
        k: len(idx.by_kind(k)) for k in ("dimension", "elevation", "grid", "callout", "note", "revision", "angle")
    }
    lines.append("")
    lines.append("Also indexed: " + ", ".join(f"{v} {k}s" for k, v in counts.items() if v))
    return "\n".join(lines)


def scope_advice(idx: Index) -> list[str]:
    """Friendly nudges for the two things this app handles badly: a multi-discipline combined set
    (it only answers structural questions) and a set large enough to be slow / memory-heavy to index."""
    notices = []
    # The discipline is the sheet number's letter prefix, with or without a separator ("S-402", "S.4", "S402").
    # A synthetic "P<page>" fallback (sheet number never found) is not a discipline, so it is not counted.
    prefixes = Counter(
        m.group(1)
        for s in idx.sheets
        if s.number != f"P{s.page}" and (m := re.match(r"^([A-Z]{1,2})[-.]?\d", s.number))
    )
    structural = prefixes.pop("S", 0)
    classified = structural + sum(prefixes.values())
    # A set where one prefix covers >= 70% of the classified sheets is single-discipline by construction, whatever
    # the letter: "S" is not the only structural prefix (some sets use "B" for bracing/slab/foundation sheets).
    dominant_share = max([structural, *prefixes.values()], default=0) / classified if classified else 0
    # A sheet whose real number was never found falls back to a synthetic "P<page>" (see
    # `_titleblock_runs`'s default `SheetMeta.number`) -- that "P" happens to also match the
    # discipline-prefix shape above, so a set where sheet-number resolution is itself unreliable
    # (many sheets never got a real number) could count those synthetic fallbacks as a "P"
    # discipline and confidently declare "multi-discipline" from data it shouldn't trust at all.
    # Degrade gracefully instead: skip the warning when too much of the classified set is synthetic.
    synthetic = sum(1 for s in idx.sheets if s.number == f"P{s.page}")
    reliable = len(idx.sheets) == 0 or synthetic / len(idx.sheets) < 0.3
    if classified >= 6 and prefixes and structural < classified * 0.5 and dominant_share < 0.7 and reliable:
        others = ", ".join(f"{k} ({v})" for k, v in prefixes.most_common())
        notices.append(
            f"This looks like a multi-discipline combined set — only {structural} of {classified} classified "
            f"sheet(s) are structural (S-prefixed); the rest look like {others}. This reader only answers "
            "structural questions, so pointing it at a structural-only PDF will index faster and give cleaner results."
        )
    n = len(idx.sheets)
    est_mb = (
        sum(
            (s.width / 72 * render_dpi_for(s.width, s.height)) * (s.height / 72 * render_dpi_for(s.width, s.height)) * 3
            for s in idx.sheets
        )
        / 1e6
    )
    if n > 40 or est_mb > 2000:
        notices.append(
            f"This is a large set ({n} sheets) — indexing it can take a minute or more and use several GB of RAM. "
            "If you only need some of the sheets, trimming the PDF down first will be quicker and lighter."
        )
    # Duplicate sheet numbers: the Index has no collision handling. `sheet_by_number` returns the
    # first match, and every fact from the other physical page is filed under the same, now
    # ambiguous number. It happens for two reasons: two pages resolve to the same number by accident,
    # or the PDF itself reuses a number (an unfilled template page). Saying so tells the user that
    # answers for that number may mix two physical pages.
    dupes = [num for num, c in Counter(s.number for s in idx.sheets).items() if c > 1]
    if dupes:
        notices.append(
            f"Sheet number(s) appear more than once in this set: {', '.join(sorted(dupes))}. "
            "Answers scoped to one of these numbers may be mixing facts from more than one physical page."
        )
    return notices
