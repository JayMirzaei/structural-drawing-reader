"""OCR for scanned drawings: a raster page becomes the same text runs a vector PDF gives.

The engine is an optional dependency (install the `ocr` extra). Without it a scan is ingested with no
text. Conventions this path assumes, and the vector path does not need:

- OCR text is approximate (O/0, S/5 confusions). Each run carries the engine's confidence, and facts
  built from OCR text are capped below vector confidence (`config.OCR_CONF_CAP`).
- Upright text is read first; a tiled pass re-reads dimensioned drawings at scan resolution, and a
  rotated pass reads text running up the page.
- Circles are not recovered from a scan, so rules that need them (grid bubbles, elevation markers)
  find nothing. Long straight lines are recovered, so dimension lines can be matched.
"""

from drawing_reader.ocr import config
from drawing_reader.ocr.engine import available, ocr_page, ocr_tiled, ocr_vertical, text_height_pt
from drawing_reader.ocr.raster import is_scanned_page, native_scale, raster_segments, titleblock_left_x
from drawing_reader.ocr.runs import fix_vertical, merge_runs, regroup, repair_drawing_numbers

__all__ = [
    "available",
    "config",
    "fix_vertical",
    "is_scanned_page",
    "merge_runs",
    "native_scale",
    "ocr_page",
    "ocr_tiled",
    "ocr_vertical",
    "raster_segments",
    "regroup",
    "repair_drawing_numbers",
    "text_height_pt",
    "titleblock_left_x",
]
