"""Measure how faithfully the OCR path reads a drawing.

Vector pages are rasterised into an image-only PDF (a stand-in for a scan), the real pipeline is run
on it, and each kind of fact is compared with what the same drawing gives as real text.

    uv run --extra ocr python eval/ocr_fidelity.py <vector.pdf> [--pages N] [--dpi 150]
        [--modes first,tiled,vertical,all] [--set NAME=VALUE ...]

Pages: the N with the most numbers (dimensioned drawings, where the passes differ). Modes: `first` is
the first OCR pass only; `tiled` adds the tiled pass; `vertical` adds the rotated pass for vertical
text; `all` is everything. `--set` overrides an `ocr.config` constant for the run, to try settings.
Nothing is written outside a temporary folder.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import re
import tempfile
import time
from pathlib import Path

import pymupdf

from drawing_reader.ingest import ingest
from drawing_reader.ocr import config
from drawing_reader.parse import build_index


def raster_pdf(src: Path, pages: list[int], dpi: int, out: Path) -> None:
    """Image-only copy of the chosen pages (grey, JPEG-compressed like a scan)."""
    doc, new = pymupdf.open(src), pymupdf.open()
    for p in pages:
        pix = doc[p].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        page = new.new_page(width=doc[p].rect.width, height=doc[p].rect.height)
        page.insert_image(page.rect, stream=pix.tobytes("jpeg", jpg_quality=70))
    new.save(out)


def vector_pdf(src: Path, pages: list[int], out: Path) -> None:
    """The same pages as real text: the truth the scan is compared with."""
    doc, new = pymupdf.open(src), pymupdf.open()
    for p in pages:
        new.insert_pdf(doc, from_page=p, to_page=p)
    new.save(out)


def pick_pages(src: Path, n: int) -> list[int]:
    doc = pymupdf.open(src)
    score = [
        (sum(bool(re.fullmatch(r"\d{2,6}", w[4])) for w in page.get_text("words")), i) for i, page in enumerate(doc)
    ]
    return sorted(i for _, i in sorted(score, reverse=True)[:n])


def norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def numbers(runs) -> collections.Counter:
    return collections.Counter(w for r in runs for w in re.findall(r"[A-Z0-9]{2,}", r.text.upper()) if w.isdigit())


def shingles(runs) -> collections.Counter:
    """4-character shingles of a page's text with spaces dropped (robust to OCR merging or splitting words)."""
    s = norm("".join(r.text for r in runs))
    return collections.Counter(s[i : i + 4] for i in range(max(0, len(s) - 3)))


def recall_precision(truth: collections.Counter, read: collections.Counter) -> tuple[float, float]:
    common = sum((truth & read).values())
    return common / max(1, sum(truth.values())), common / max(1, sum(read.values()))


def share_equal(truth: list[str], read: list[str], close: bool = False) -> float:
    """Share of the non-empty truth values that were read the same (or, with `close`, at least 80% alike)."""
    pairs = [(norm(t), norm(r)) for t, r in zip(truth, read, strict=False) if t]
    if not pairs:
        return float("nan")
    same = sum(1 for t, r in pairs if (difflib.SequenceMatcher(None, t, r).ratio() >= 0.8 if close else t == r))
    return same / len(pairs)


def compare(vec_idx, vec_doc, ocr_idx, ocr_doc) -> dict:
    text_truth, text_read = collections.Counter(), collections.Counter()
    num_truth, num_read = collections.Counter(), collections.Counter()
    for vec_sheet, ocr_sheet in zip(vec_doc.sheets, ocr_doc.sheets, strict=False):
        text_truth.update(shingles(vec_sheet.runs))
        text_read.update(shingles(ocr_sheet.runs))
        num_truth.update(numbers(vec_sheet.runs))
        num_read.update(numbers(ocr_sheet.runs))
    out = {"text": recall_precision(text_truth, text_read), "numbers": recall_precision(num_truth, num_read)}
    keys = {
        "dimension": lambda f: (f.page, re.sub(r"\D", "", f.value)),
        "label": lambda f: (f.page, f.attrs.get("section", "").upper().replace(" ", "")),
    }
    for kind, key in keys.items():
        truth = collections.Counter(key(f) for f in vec_idx.by_kind(kind))
        read = collections.Counter(key(f) for f in ocr_idx.by_kind(kind))
        out[kind] = (*recall_precision(truth, read), sum(truth.values()), sum(read.values()))
    out["sheet_no"] = share_equal([s.number for s in vec_idx.sheets], [s.number for s in ocr_idx.sheets])
    out["title"] = share_equal([s.title for s in vec_idx.sheets], [s.title for s in ocr_idx.sheets], close=True)
    out["scale"] = share_equal([s.scale for s in vec_idx.sheets], [s.scale for s in ocr_idx.sheets])
    out["note_chars"] = (
        sum(len(f.source_text) for f in vec_idx.by_kind("note")),
        sum(len(f.source_text) for f in ocr_idx.by_kind("note")),
    )
    return out


def override(setting: str) -> None:
    """Apply one `NAME=VALUE` override to `ocr.config`, keeping the constant's type."""
    name, value = setting.split("=", 1)
    current = getattr(config, name)
    setattr(config, name, value == "1" if isinstance(current, bool) else type(current)(float(value)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--modes", default="first,tiled,vertical,all")
    parser.add_argument(
        "--set", action="append", default=[], metavar="NAME=VALUE", help="override an ocr.config constant"
    )
    args = parser.parse_args()
    for setting in args.set:
        override(setting)

    pages = pick_pages(args.pdf, args.pages)
    tmp = Path(tempfile.mkdtemp(prefix="ocr_fidelity_"))
    vector_pdf(args.pdf, pages, tmp / "vector.pdf")
    raster_pdf(args.pdf, pages, args.dpi, tmp / "scan.pdf")
    vec_doc = ingest(tmp / "vector.pdf", tmp / "cache_vector")
    vec_idx = build_index(vec_doc)
    print(
        f"{args.pdf.name}: pages {[p + 1 for p in pages]} at {args.dpi} dpi; vector truth: "
        f"{len(vec_idx.by_kind('dimension'))} dimensions, {len(vec_idx.by_kind('label'))} labels"
    )

    def rp(pair) -> str:
        return f"R{pair[0]:.2f} P{pair[1]:.2f}"

    def share(value: float) -> str:
        return "n/a" if value != value else f"{value:.2f}"

    for mode in args.modes.split(","):
        config.TILE_ENABLED = mode in ("tiled", "all")
        config.VOCR_ENABLED = mode in ("vertical", "all")
        started = time.time()
        ocr_doc = ingest(tmp / "scan.pdf", tmp / f"cache_{mode}")
        r = compare(vec_idx, vec_doc, build_index(ocr_doc), ocr_doc)
        print(
            f"  {mode:9} text {rp(r['text'])} | numbers {rp(r['numbers'])} | "
            f"dims {rp(r['dimension'])} ({r['dimension'][2]}->{r['dimension'][3]}) | "
            f"labels {rp(r['label'])} ({r['label'][2]}->{r['label'][3]}) | sheet# {share(r['sheet_no'])} "
            f"title {share(r['title'])} scale {share(r['scale'])} | note chars {r['note_chars'][0]}->{r['note_chars'][1]} | "
            f"{time.time() - started:.0f}s"
        )


if __name__ == "__main__":
    main()
