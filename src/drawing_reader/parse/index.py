"""Build the fact index for a whole drawing set.

Each sheet is parsed on its own by `SheetParser`; this module adds what only the set as a whole can
say: which title-block texts repeat on every sheet (project name, not a sheet title), the common
project fields, and whether each cross-reference points at a sheet that is in the set.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from drawing_reader.ingest import Document
from drawing_reader.ocr.config import OCR_CONF_CAP
from drawing_reader.parse.layout import is_horizontal, titleblock_runs
from drawing_reader.parse.location import project_location
from drawing_reader.parse.scan_repair import flag_label_misreads, repair_sheet_numbers
from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.parse.titleblock_fields import label_like
from drawing_reader.schema import Index


def _repeated_block_texts(doc: Document) -> set[str]:
    """Normalised title-block texts (any size) that recur on at least a third of a set's pages -- project, client and
    address lines. Keyed by the text and by its first 10 characters, so an OCR set's slightly different readings of
    one printed line still match. Used to keep such lines out of a sheet title."""

    def keyed(t):
        return re.sub(r"[^a-z0-9]", "", t.lower())

    per_sheet = [
        {keyed(r.text) for r in titleblock_runs(sh) if is_horizontal(r) and len(keyed(r.text)) >= 6}
        for sh in doc.sheets
    ]
    need = max(3, len(doc.sheets) // 3)
    exact = Counter()
    lens: dict[str, list[int]] = {}
    for keys in per_sheet:
        exact.update(keys)
        for k in keys:
            lens.setdefault(k[:10], []).append(len(k))
    # a reading of one printed line differs from another by a few characters, so the prefix match also needs a
    # like length ("STRUCTURAL STEEL NOTES" and "STRUCTURAL STEEL CONVEYOR PLANS" are two titles, not one line)
    return {
        k
        for keys in per_sheet
        for k in keys
        if exact[k] >= need or sum(abs(n - len(k)) <= 3 for n in lens[k[:10]]) >= need
    }


def _common_large_texts(doc: Document) -> set[str]:
    """Texts that repeat in the title block of most sheets (project name, client) are not sheet titles.
    On an OCR'd set the same printed text is read slightly differently on each page ("Harlow
    UTILITIES" -> "arlowUTILITIES", "HarIowUTILITIES"), so there "repeats" means "near-
    identical after dropping case and non-alphanumerics" (difflib ratio >= 0.8)."""
    per_sheet: list[set[str]] = []
    for s in doc.sheets:
        big = [r for r in titleblock_runs(s) if is_horizontal(r)]
        if not big:
            continue
        top = max(r.size for r in big)
        # a scan's repeated header lines (project, location) are smaller than the logo that sets `top`
        per_sheet.append({r.text for r in big if r.size >= (0.55 if doc.from_ocr else 0.75) * top})
    n = len(doc.sheets)
    need = max(2, 0.6 * n)
    if doc.from_ocr:

        def key(t: str) -> str:
            return re.sub(r"[^a-z0-9]", "", t.lower())

        keys = [{key(t) for t in texts if len(key(t)) >= 6} for texts in per_sheet]

        def pages_with(k: str) -> int:
            # "SHEET 1" vs "SHEET 2" differ in one digit but are different titles: digits must agree
            return sum(
                any(
                    k == o
                    or (re.sub(r"\D", "", k) == re.sub(r"\D", "", o) and SequenceMatcher(None, k, o).ratio() >= 0.8)
                    for o in ks
                )
                for ks in keys
            )

        return {t for texts in per_sheet for t in texts if n > 1 and len(key(t)) >= 6 and pages_with(key(t)) >= need}
    cnt: Counter = Counter()
    for texts in per_sheet:
        cnt.update(texts)
    return {t for t, c in cnt.items() if n > 1 and c >= need}


def build_index(doc: Document) -> Index:
    common = _common_large_texts(doc)
    idx = Index(doc_id=doc.doc_id, source=doc.source, is_vector=doc.is_vector, from_ocr=doc.from_ocr)
    project_fields: Counter = Counter()
    repeated = _repeated_block_texts(doc)
    for s in doc.sheets:
        sp = SheetParser(s)
        sp.repeated = repeated
        meta, facts = sp.run(common)
        idx.sheets.append(meta)
        idx.facts.extend(facts)
        for k, v in meta.fields.items():
            project_fields[(k, v)] += 1
    # "name" is meant to be the project's own repeated title text -- but any other title-block
    # field that also happens to repeat consistently (Job No., Date, Approved By, Drawn By, Scale)
    # equally clears _common_large_texts' own "large, repeated" bar, so without this exclusion it
    # gets joined into "name" too, producing a garbled blob of several unrelated fields
    # ("3100412 / 2031-05-14 / 4 / AS NOTED / WAREHOUSE EXPANSION / A.B. ARCHITECT / V.Q. / Z.H.")
    # even on templates where every one of those fields is already correctly extracted
    # and labeled on its own right below it.
    threshold = max(2, 0.6 * len(doc.sheets))
    # A list, not a set: preserves project_fields' original insertion order (a bare set's iteration
    # order isn't guaranteed stable, which would make idx.project's row order flap between runs).
    common_fields = [(k, v) for (k, v), c in project_fields.items() if c >= threshold]
    recognized_values = {v for _, v in common_fields}
    # Purely numeric/punctuation texts ("4" from "Sheet Number 4 of 4") are page furniture, not a name.
    name_texts = sorted(
        t for t in common if t not in recognized_values and re.search(r"[A-Za-z]", t) and not label_like(t)
    )
    idx.project = {"name": " / ".join(name_texts)} if name_texts else {}
    for k, v in common_fields:
        if k not in ("Scale",):
            idx.project[k] = v
    loc = project_location(idx)
    if loc:
        idx.project["Location"] = loc
    if doc.from_ocr:
        repair_sheet_numbers(idx, doc)
    _resolve_reference_targets(idx)
    if doc.from_ocr:
        flag_label_misreads(idx)
        # Convention: text read from a scan is approximate (O/0, C/O confusions), so no fact
        # built from it may claim vector-level certainty; the flag lets the UI say "from a scan".
        for f in idx.facts:
            f.confidence = min(f.confidence, OCR_CONF_CAP)
            f.attrs["ocr"] = True
    return idx


def _resolve_reference_targets(idx: Index) -> None:
    """Cross-sheet: mark each reference/callout target as in the set or not. A target that is no sheet number
    but equals a view/detail title on some sheet ("3 / DX-04", "2 / K7-02B": detail marks shaped like sheet ids)
    is a reference to that view, not a missing sheet."""
    have = set(idx.sheet_numbers())
    view_sheet: dict[str, str] = {}
    for v in idx.by_kind("view"):
        view_sheet.setdefault(re.sub(r"\s", "", (v.attrs.get("title") or v.value).upper()), v.sheet)
    for f in idx.by_kind("reference", "callout"):
        tgt = f.attrs.get("target_sheet", "")
        in_set = any(sheet_ref_matches(tgt, h) for h in have)
        if not in_set and re.sub(r"\s", "", tgt.upper()) in view_sheet:
            in_set = True
            f.attrs["target_view_sheet"] = view_sheet[re.sub(r"\s", "", tgt.upper())]
        f.attrs["target_in_set"] = in_set
