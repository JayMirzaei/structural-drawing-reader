"""Snapshot regression net for local folders of drawings kept outside the repository.

Hand-written expected answers only exist for drawings that can live in the repository. For any other
set (drawings kept on one machine), this module freezes the reader's *current* behaviour into
a local snapshot file and later diffs fresh behaviour against it. A diff does not mean "wrong"; it
means "changed since a person last confirmed it", the same idea as a visual-regression test. Update a
snapshot deliberately, after checking that the change is an improvement.

Any PDF under the drawings folder is picked up; no per-set test code is needed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from drawing_reader.ingest import ingest
from drawing_reader.parse import build_index
from drawing_reader.qa import answer, scope_advice

# Structure-level questions only: they mean something for any structural drawing set, unlike
# questions about one set's members or elevations.
GENERIC_PROBES = [
    "List the sheets and their titles.",
    "What is the project number?",
    "What is the latest revision on each sheet?",
    "Which sheets are referenced but not in the set?",
    "What grid lines are there?",
]

# A large combined multi-discipline PDF (around 100 large-format sheets) costs orders of magnitude
# more to ingest and parse than a typical structural-only set. File size is a free proxy for that
# cost: it needs no parsing, so a test run can sort files into a fast and a slow tier before doing any
# work.
SLOW_FILE_SIZE_MB = 20


def discover_pdfs(drawings_dir: Path, exclude: tuple[str, ...] = ()) -> list[Path]:
    """Every PDF under `drawings_dir`, except file names listed in `exclude`."""
    if not drawings_dir.exists():
        return []
    return sorted(p for p in drawings_dir.rglob("*.pdf") if p.name not in exclude)


def is_slow_pdf(pdf: Path) -> bool:
    """True for a PDF big enough that it belongs in an opt-in slow test tier (see SLOW_FILE_SIZE_MB).

    The big combined sets are the messiest files and the most likely to expose scaling problems, so
    they are worth keeping in the net, just not on every run."""
    return pdf.stat().st_size > SLOW_FILE_SIZE_MB * 1024 * 1024


def snapshot_path(pdf: Path, drawings_dir: Path, snapshot_dir: Path) -> Path:
    """Where the snapshot of `pdf` is kept: its path under `drawings_dir`, flattened to a file name."""
    rel = pdf.relative_to(drawings_dir)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(rel)).strip("_")
    return snapshot_dir / f"{slug}.json"


def build_snapshot(pdf: Path, drawings_dir: Path, cache_dir: Path) -> dict:
    """The reader's behaviour on one PDF, as a small JSON-serialisable dict."""
    idx = build_index(ingest(pdf, cache_dir))
    fact_counts: dict[str, int] = {}
    for f in idx.facts:
        fact_counts[f.kind] = fact_counts.get(f.kind, 0) + 1
    probes = {}
    for q in GENERIC_PROBES:
        a = answer(q, idx, llm=None)
        probes[q] = {"rule": a.method, "confidence": round(a.confidence, 2), "text": a.text}
    # Coarse "is this suspiciously empty" counts. An empty project block or dozens of blank sheet
    # titles is easy to miss when no probe question happens to touch it; as a count it shows up in the
    # diff.
    any_fact_sheets = {f.sheet for f in idx.facts}
    titleblock_sheets = {f.sheet for f in idx.by_kind("titleblock")}
    sparseness = {
        "blank_title_sheets": sum(1 for s in idx.sheets if not s.title),
        "sheets_with_no_facts_at_all": sum(1 for s in idx.sheets if s.number not in any_fact_sheets),
        "sheets_with_no_titleblock_facts": sum(1 for s in idx.sheets if s.number not in titleblock_sheets),
        "project_fields_found": len(idx.project),
    }
    return {
        "source": str(pdf.relative_to(drawings_dir)),
        "is_vector": idx.is_vector,
        "sheet_count": len(idx.sheets),
        "fact_counts": dict(sorted(fact_counts.items())),
        "scope_advice": scope_advice(idx),
        "sparseness": sparseness,
        "probes": probes,
    }


def diff_snapshots(old: dict, new: dict) -> list[str]:
    """Human-readable differences between two snapshots; empty when behaviour is unchanged."""
    diffs = []
    for key in ("sheet_count", "is_vector"):
        if old.get(key) != new.get(key):
            diffs.append(f"{key}: {old.get(key)!r} -> {new.get(key)!r}")
    if old.get("scope_advice") != new.get("scope_advice"):
        diffs.append(f"scope_advice: {old.get('scope_advice')!r} -> {new.get('scope_advice')!r}")
    for section in ("fact_counts", "sparseness"):
        old_s, new_s = old.get(section, {}), new.get(section, {})
        for key in sorted(set(old_s) | set(new_s)):
            ov, nv = old_s.get(key, 0), new_s.get(key, 0)
            if ov != nv:
                diffs.append(f"{section}[{key}]: {ov} -> {nv}")
    old_p, new_p = old.get("probes", {}), new.get("probes", {})
    for q in sorted(set(old_p) | set(new_p)):
        o, n = old_p.get(q), new_p.get(q)
        if o != n:
            diffs.append(f"probe {q!r}:\n    was: {o}\n    now: {n}")
    return diffs


def check_folder(drawings_dir: Path, snapshot_dir: Path, cache_dir: Path, update: bool = False) -> dict[str, list[str]]:
    """Compare (or, with `update`, rewrite) the snapshot of every PDF under `drawings_dir`.

    Returns {relative pdf path: differences}; a PDF with no snapshot yet reports that as its one
    difference."""
    report: dict[str, list[str]] = {}
    for pdf in discover_pdfs(drawings_dir):
        rel = str(pdf.relative_to(drawings_dir))
        path = snapshot_path(pdf, drawings_dir, snapshot_dir)
        fresh = build_snapshot(pdf, drawings_dir, cache_dir)
        if update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(fresh, indent=1, sort_keys=True) + "\n")
            report[rel] = []
        elif not path.exists():
            report[rel] = ["no snapshot yet: update to create one"]
        else:
            report[rel] = diff_snapshots(json.loads(path.read_text()), fresh)
    return report
