"""On-disk cache of extracted primitives and of each OCR pass.

Everything is keyed by a hash of the PDF bytes. OCR results are kept per page and per pass version,
apart from the primitives file, so a changed parse rule or a re-extraction never repeats the slow OCR.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from drawing_reader import ocr
from drawing_reader.ingest.primitives import Circle, Document, Segment, Sheet, TextRun
from drawing_reader.ingest.vector import decode_symbol_font


def write_atomic(path: Path, data: bytes | str) -> None:
    """Write a cache file so that no reader ever sees it half written.

    The bytes go to a temporary file in the same folder, which then replaces `path` in one step
    (`os.replace` is atomic on one file system). Two processes ingesting the same PDF at once (parallel
    test workers, two app sessions) each write a complete file, and the last one wins; a reader sees
    the old file, or the new one, never a truncated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode() if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


# Version of the primitives.json layout. A file with another version is not read, and the PDF is ingested again.
CACHE_FORMAT = 2


def primitives_cache_path(out: Path) -> Path:
    return out / "primitives.json"


def write_document(out: Path, doc: Document) -> None:
    """Cache a Document as out/primitives.json. Page images are stored relative to `out`, so the cache folder can be
    used from any working directory and moved as a whole."""
    data = asdict(doc)
    data["cache_format"] = CACHE_FORMAT
    for s in data["sheets"]:
        s["image_path"] = Path(s["image_path"]).name if s["image_path"] else ""
    write_atomic(primitives_cache_path(out), json.dumps(data))


def load_document(out: Path) -> Document | None:
    """The Document a previous ingest() call cached in `out`, or None when there is none in the current format.

    Valid as long as the source PDF's bytes are unchanged (doc_id, the cache key, is a hash of those bytes). Image
    paths are resolved against `out`."""
    path = primitives_cache_path(out)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return None
    if data.get("cache_format") != CACHE_FORMAT:
        return None
    sheets = []
    for s in data["sheets"]:
        runs = [
            TextRun(
                id=r["id"],
                text=decode_symbol_font(r["text"]),
                bbox=tuple(r["bbox"]),
                dir=tuple(r["dir"]),
                size=r["size"],
                block=r["block"],
                conf=r.get("conf", 1.0),
            )
            for r in s["runs"]
        ]
        segments = [
            Segment(p1=tuple(g["p1"]), p2=tuple(g["p2"]), width=g["width"], dashed=g["dashed"]) for g in s["segments"]
        ]
        circles = [Circle(bbox=tuple(c["bbox"]), arcs=c["arcs"], width=c["width"]) for c in s["circles"]]
        rects = [tuple(r) for r in s["rects"]]
        sheets.append(
            Sheet(
                index=s["index"],
                width=s["width"],
                height=s["height"],
                runs=runs,
                segments=segments,
                circles=circles,
                rects=rects,
                image_path=str(out / s["image_path"]) if s["image_path"] else "",
                image_scale=s["image_scale"],
                titleblock_x=s.get("titleblock_x"),
                ocr_tiles=s.get("ocr_tiles", 0),
                ocr_tile_scale=s.get("ocr_tile_scale", 0.0),
                ocr_text_pt=s.get("ocr_text_pt", 0.0),
                ocr_vertical_tiles=s.get("ocr_vertical_tiles", 0),
            )
        )
    return Document(
        doc_id=data["doc_id"],
        source=data["source"],
        sheets=sheets,
        is_vector=data["is_vector"],
        from_ocr=data.get("from_ocr", False),
        ocr_version=data.get("ocr_version", 0),
        seg_version=data.get("seg_version", 0),
        vocr_version=data.get("vocr_version", 0),
        tile_version=data.get("tile_version", 0),
    )


def _page_ocr_path(out: Path, i: int) -> Path:
    return out / "ocr" / f"p{i + 1}_v{ocr.config.OCR_VERSION}.json"


def read_page_ocr(out: Path, i: int):
    """One page's OCR result from an earlier read, or None. Kept per page and per OCR_VERSION, apart from
    primitives.json, so re-extracting a PDF (or a changed parse rule) never repeats the slow OCR; an empty result
    is kept too, so a page OCR found nothing on (a map, a photo) is not read again."""
    f = _page_ocr_path(out, i)
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text())
        runs = [
            TextRun(
                id=r["id"],
                text=r["text"],
                bbox=tuple(r["bbox"]),
                dir=tuple(r["dir"]),
                size=r["size"],
                block=r["block"],
                conf=r.get("conf", 1.0),
            )
            for r in d["runs"]
        ]
        return runs, d.get("titleblock_x")
    except (OSError, ValueError, KeyError):
        return None


def write_page_ocr(out: Path, i: int, runs: list, titleblock_x) -> None:
    f = _page_ocr_path(out, i)
    write_atomic(f, json.dumps({"runs": [asdict(r) for r in runs], "titleblock_x": titleblock_x}))


def _read_pass_cache(f: Path):
    """(runs, info) of a supplementary pass's cache file {"runs", "info"}."""
    d = json.loads(f.read_text())
    rows, info = d["runs"], d.get("info", {})
    return [
        TextRun(
            id=r["id"],
            text=r["text"],
            bbox=tuple(r["bbox"]),
            dir=tuple(r["dir"]),
            size=r["size"],
            block=r["block"],
            conf=r.get("conf", 1.0),
        )
        for r in rows
    ], info


def page_tiled_runs(out: Path, i: int, page, text_pt: float | None = None):
    """The tiled second pass (`ocr.ocr_tiled`), kept per page and TILE_VERSION, with how it was read (tiles, scale):
    (runs, info)."""
    f = out / "ocr_t" / f"p{i + 1}_v{ocr.config.TILE_VERSION}.json"
    if f.exists():
        try:
            return _read_pass_cache(f)
        except (OSError, ValueError, KeyError):
            pass
    runs, info = ocr.ocr_tiled(page, i, TextRun, text_pt)
    write_atomic(f, json.dumps({"runs": [asdict(r) for r in runs], "info": info}))
    return runs, info


def page_vertical_runs(out: Path, i: int, page, known: list, text_pt: float | None = None):
    """Vertical text found by the rotated second pass (`ocr.ocr_vertical`), kept per page and VOCR_VERSION: (runs,
    info)."""
    f = out / "ocr_v" / f"p{i + 1}_v{ocr.config.VOCR_VERSION}.json"
    if f.exists():
        try:
            return _read_pass_cache(f)
        except (OSError, ValueError, KeyError):
            pass
    runs, info = ocr.ocr_vertical(page, i, TextRun, known, text_pt)
    write_atomic(f, json.dumps({"runs": [asdict(r) for r in runs], "info": info}))
    return runs, info


def page_segments(out: Path, i: int, page) -> list:
    """Raster-found lines of a scanned page (`ocr.raster_segments`), kept per page and SEG_VERSION like the OCR
    itself."""
    f = out / "seg" / f"p{i + 1}_v{ocr.config.SEG_VERSION}.json"
    if f.exists():
        try:
            return [
                Segment(p1=tuple(g["p1"]), p2=tuple(g["p2"]), width=g["width"], dashed=g["dashed"])
                for g in json.loads(f.read_text())
            ]
        except (OSError, ValueError, KeyError):
            pass
    segs = ocr.raster_segments(page, Segment)
    write_atomic(f, json.dumps([asdict(g) for g in segs]))
    return segs
