"""PDF ingestion: every page of a drawing PDF becomes primitives plus a rendered image.

`ingest` runs four steps: reuse the cache when it is still valid, open the PDF (rejecting files that
cannot be read), extract each page's vector text and geometry and render it, and, when the OCR extra is
installed, read the pages that have no usable text layer from their pixels.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from drawing_reader import ocr
from drawing_reader.ingest.cache import (
    file_hash,
    load_document,
    page_segments,
    page_tiled_runs,
    page_vertical_runs,
    read_page_ocr,
    write_atomic,
    write_document,
    write_page_ocr,
)
from drawing_reader.ingest.primitives import Document, Sheet, TextRun
from drawing_reader.ingest.rendering import RENDER_DPI, render_dpi_for
from drawing_reader.ingest.vector import extract_geometry, extract_runs


class UnreadablePDF(ValueError):
    """The file cannot be read as a drawing set: not a PDF, damaged, password-protected or empty.

    The message is written for the person who chose the file."""


def load_cached(pdf_path: str | Path, cache_dir: str | Path) -> Document | None:
    """The cached Document for this PDF exactly as stored -- never extracts, renders or OCRs. For analysis scripts that
    re-run the parser over text already read; None when the PDF has not been ingested yet."""
    return load_document(Path(cache_dir).resolve() / file_hash(Path(pdf_path).read_bytes()))


def ingest(pdf_path: str | Path, cache_dir: str | Path, dpi: int = RENDER_DPI) -> Document:
    """Read a PDF, extract primitives per page, render page PNGs into cache_dir/<doc_id>/.

    Extracted primitives (text runs, geometry) are cached to cache_dir/<doc_id>/primitives.json,
    keyed by a hash of the PDF's own bytes -- a byte-identical PDF always reuses the cache, any
    change to the PDF gets a fresh doc_id and skips it. This only caches PyMuPDF's raw extraction;
    build_index() (the actual parsing rules) always re-runs from these primitives on every call.

    Raises UnreadablePDF when the file is not a readable PDF with at least one page.
    """
    pdf_path = Path(pdf_path)
    data = pdf_path.read_bytes()
    doc_id = file_hash(data)
    out = Path(cache_dir).resolve() / doc_id
    cached = load_document(out)
    if cached is not None and not _needs_new_ocr(cached):
        return cached

    pdf = open_pdf(data)
    out.mkdir(parents=True, exist_ok=True)
    sheets = [_vector_sheet(page, i, out, dpi) for i, page in enumerate(pdf)]
    is_vector = sum(len(sh.runs) for sh in sheets) > 5 * len(sheets)
    from_ocr = ocr.available() and _read_scanned_pages(pdf, sheets, out)
    if from_ocr:
        ocr.repair_drawing_numbers(sheets)
    with_ocr = ocr.available()  # pass versions are recorded as 0 when OCR is not installed
    doc = Document(
        doc_id=doc_id,
        source=str(pdf_path),
        sheets=sheets,
        is_vector=is_vector,
        from_ocr=from_ocr,
        ocr_version=ocr.config.OCR_VERSION if with_ocr else 0,
        seg_version=ocr.config.SEG_VERSION if with_ocr else 0,
        vocr_version=ocr.config.VOCR_VERSION if with_ocr else 0,
        tile_version=ocr.config.TILE_VERSION if with_ocr else 0,
    )
    write_document(out, doc)
    return doc


def open_pdf(data: bytes) -> pymupdf.Document:
    """The PDF in `data`, or UnreadablePDF with a reason a user can act on."""
    if not data:
        raise UnreadablePDF("The file is empty.")
    if b"%PDF-" not in data[:1024]:  # MuPDF would otherwise open a text or image file as a document
        raise UnreadablePDF("The file is not a PDF (it does not start with a PDF header).")
    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError) as e:
        raise UnreadablePDF(f"The file is not a readable PDF ({type(e).__name__}: {str(e)[:120]}).") from None
    if not pdf.is_pdf:
        raise UnreadablePDF("The file is not a PDF.")
    if pdf.needs_pass:
        raise UnreadablePDF("The PDF is password-protected. Remove the password and try again.")
    if pdf.page_count == 0:
        raise UnreadablePDF("The PDF has no pages.")
    return pdf


def _needs_new_ocr(cached: Document) -> bool:
    """Whether a cached document should be read again because the OCR available now differs from the one it was read
    with: OCR installed since a scan was cached (version 0), or a newer OCR pass version. A mostly-vector set with a
    page that had almost no text (an outlined-lettering page in a combined set) counts too; a fully-texted vector set
    never does."""
    if not ocr.available():
        return False
    cfg = ocr.config
    if cached.ocr_version != cfg.OCR_VERSION and (
        not cached.is_vector or any(sum(len(r.text) for r in sh.runs) < cfg.TRIVIAL_TEXT_CHARS for sh in cached.sheets)
    ):
        return True
    return cached.from_ocr and (
        cached.seg_version != cfg.SEG_VERSION
        or cached.vocr_version != cfg.VOCR_VERSION
        or cached.tile_version != cfg.TILE_VERSION
    )


def _vector_sheet(page: pymupdf.Page, i: int, out: Path, dpi: int) -> Sheet:
    """One page's text runs and geometry as the PDF stores them, plus its rendered PNG (kept in the cache)."""
    runs = extract_runs(page, i)
    segs, circs, rects = extract_geometry(page)
    img_path = out / f"sheet_{i + 1}.png"
    eff = render_dpi_for(page.rect.width, page.rect.height, dpi)
    if img_path.exists():
        png_width = pymupdf.Pixmap(str(img_path)).width
    else:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(eff / 72, eff / 72))
        write_atomic(img_path, pix.tobytes("png"))
        png_width = pix.width
    return Sheet(
        index=i,
        width=page.rect.width,
        height=page.rect.height,
        runs=runs,
        segments=segs,
        circles=circs,
        rects=rects,
        image_path=str(img_path),
        image_scale=png_width / page.rect.width,
    )


def _read_scanned_pages(pdf: pymupdf.Document, sheets: list[Sheet], out: Path) -> bool:
    """OCR every page that needs it, decided per page so a vector page in a mixed set is left alone. True when any
    page's text now comes from OCR."""
    from_ocr = False
    corner, corner_bar = _corner_run_counts(sheets)
    for i, page in enumerate(pdf):
        sheet = sheets[i]
        layer = _thin_text_layer(page, sheet, corner[i] < corner_bar)
        got = _first_ocr_pass(page, i, sheet, out, layer)
        if got is None:
            continue
        sheet.runs, sheet.titleblock_x = got
        if layer:
            sheet.runs = ocr.merge_runs(sheet.runs, layer)  # the text layer is exact: it wins where the two overlap
        from_ocr = True
        if len(sheet.segments) < ocr.config.OUTLINED_MIN_PATHS:
            sheet.segments = page_segments(out, i, page)  # a scan has no vector lines: find them in the raster
        if _is_dimensioned(sheet):
            _extra_ocr_passes(page, i, sheet, out)
    return from_ocr


def _corner_run_counts(sheets: list[Sheet]) -> tuple[list[int], float]:
    """Text runs in each page's title-block corner, and the count below which a page's text layer is suspect.

    A scan's hidden text layer can miss one sheet's title block: its corner then holds far fewer runs than its
    sibling sheets'."""
    corner = [sum(1 for r in sh.runs if r.bbox[0] > 0.55 * sh.width and r.bbox[1] > 0.85 * sh.height) for sh in sheets]
    if len(corner) >= 3:
        return corner, max(ocr.config.CORNER_MIN_RUNS, 0.5 * sorted(corner)[len(corner) // 2])
    return corner, ocr.config.CORNER_MIN_RUNS


def _thin_text_layer(page: pymupdf.Page, sheet: Sheet, sparse_corner: bool) -> list[TextRun]:
    """A scanned page's own text layer, when it has one but it is too thin to trust alone: its runs, renamed so they
    do not clash with OCR run ids, to be merged into the OCR result. Empty when the page needs no merge."""
    nchars = sum(len(r.text) for r in sheet.runs)
    cfg = ocr.config
    if not (
        cfg.TRIVIAL_TEXT_CHARS <= nchars
        and (nchars < cfg.THIN_LAYER_CHARS or sparse_corner)
        and ocr.is_scanned_page(page)
    ):
        return []
    return [
        TextRun(
            id=r.id.replace(".t", ".m"), text=r.text, bbox=r.bbox, dir=r.dir, size=r.size, block=r.block, conf=r.conf
        )
        for r in sheet.runs
    ]


def _first_ocr_pass(page: pymupdf.Page, i: int, sheet: Sheet, out: Path, layer: list[TextRun]):
    """(runs, title-block x) of the page's first OCR pass, from the cache or read now; None when the page has a usable
    text layer of its own (a stray word, such as a page number or a stamp, does not count as one)."""
    nchars = sum(len(r.text) for r in sheet.runs)
    if nchars >= ocr.config.TRIVIAL_TEXT_CHARS and not layer:
        return None
    got = read_page_ocr(out, i)
    if got is None and (ocr.is_scanned_page(page) or layer):
        got = (ocr.ocr_page(page, i, TextRun), ocr.titleblock_left_x(page))
        write_page_ocr(out, i, *got)
    return got


def _is_dimensioned(sheet: Sheet) -> bool:
    """Enough numbers or runs that the page is a dimensioned drawing, worth the slower OCR passes."""
    numbers = sum(bool(re.fullmatch(r"\d{2,6}", r.text.strip())) for r in sheet.runs)
    return numbers >= ocr.config.TILE_MIN_NUMBERS or len(sheet.runs) >= ocr.config.TILE_MIN_RUNS


def _extra_ocr_passes(page: pymupdf.Page, i: int, sheet: Sheet, out: Path) -> None:
    """Read a dimensioned scan again: tile by tile at its own resolution, then, when much of its text runs up the
    page, rotated for vertical text."""
    if ocr.config.TILE_ENABLED:
        text_pt = ocr.text_height_pt(sheet.runs)
        extra, info = page_tiled_runs(out, i, page, text_pt)
        sheet.runs = ocr.merge_runs(sheet.runs, extra)
        sheet.ocr_tiles = info.get("tiles", -1)
        sheet.ocr_tile_scale = info.get("scale", 0.0)
        sheet.ocr_text_pt = info.get("text_pt", text_pt or 0.0)
    ocr.regroup(sheet.runs)  # vertical boxes get their direction before the count below
    vertical = sum(1 for r in sheet.runs if tuple(r.dir) == (0.0, -1.0))
    if ocr.config.VOCR_ENABLED and vertical >= ocr.config.VOCR_MIN_VERTICAL:
        vruns, vinfo = page_vertical_runs(out, i, page, sheet.runs, ocr.text_height_pt(sheet.runs))
        sheet.runs = sheet.runs + vruns
        sheet.ocr_vertical_tiles = vinfo.get("tiles", -1)
        ocr.regroup(sheet.runs)


def sheet_summary(sheet: Sheet) -> dict:
    return {
        "page": sheet.index + 1,
        "text_runs": len(sheet.runs),
        "segments": len(sheet.segments),
        "circles": len(sheet.circles),
        "rects": len(sheet.rects),
        "size_pt": (round(sheet.width), round(sheet.height)),
    }
