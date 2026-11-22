"""PDF ingestion: turn each sheet of a drawing PDF into geometric primitives plus a rendered image.

Vector PDFs give exact text runs (with rotation) and line and circle geometry. Scanned pages go
through the optional OCR path, which produces the same primitives. Everything above this layer works
on the primitives only.
"""

from drawing_reader.ingest.cache import file_hash
from drawing_reader.ingest.pipeline import UnreadablePDF, ingest, load_cached, sheet_summary
from drawing_reader.ingest.primitives import Circle, Document, Segment, Sheet, TextRun
from drawing_reader.ingest.rendering import MAX_RENDER_PX, RENDER_DPI, render_dpi_for

__all__ = [
    "MAX_RENDER_PX",
    "RENDER_DPI",
    "Circle",
    "Document",
    "Segment",
    "Sheet",
    "TextRun",
    "UnreadablePDF",
    "file_hash",
    "ingest",
    "load_cached",
    "render_dpi_for",
    "sheet_summary",
]
