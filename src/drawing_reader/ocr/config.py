"""Tunable constants of the OCR path.

Kept in one module and always read as `config.NAME` so an experiment (see `eval/ocr_fidelity.py`) can
change a value at run time. The `*_VERSION` numbers are cache keys: bump one when the output of the
pass it names changes, and cached scans are re-read.
"""

from __future__ import annotations

TILE_ENABLED = True  # switches for the supplementary passes (the fidelity test turns them off one by one)


VOCR_ENABLED = True


TILE_VERSION = 2  # bump when `ocr_tiled` output changes


TILE_NATIVE_CAP = (
    3.2  # the tiled pass never renders finer than this (px per page point), nor finer than the scan itself
)


# the pass aims for lettering this many pixels tall: 6 pt text is read at ~2.7 px/pt, 10 pt text at ~1.6 (a big sheet's
# tiles then stay few)
TILE_TEXT_PX = 16


# px per page point for the tiled pass when the page has no embedded image to take the scan's own resolution from
TILE_SCALE = 2.0


TILE_PX = 1900  # tile edge: the detector shrinks anything larger than 2000 px, so a tile is read at its own resolution


TILE_OVERLAP = 250  # tiles overlap by this much, so text cut by one tile's edge is whole in the next


VOCR_MIN_VERTICAL = (
    6  # vertical boxes the upright passes must already have found before the rotated pass is worth running
)


VOCR_VERSION = 2  # bump when `ocr_vertical` output changes


TILE_MIN_NUMBERS = 12  # first-pass bare numbers that mark a dimensioned drawing


# ... or first-pass text runs that mark a dense drawing (a weak first pass reads few numbers exactly where the lettering
# is small)  # a page is given the vertical pass only if its first pass read this many bare numbers (a dimensioned
# drawing, not a text page)
TILE_MIN_RUNS = 60


SEG_MAX = 4000  # most raster segments kept per page


SEG_VERSION = 2  # bump when `raster_segments` output changes, so cached scans get their lines recomputed


OCR_VERSION = 4  # bump when OCR output changes, so cached scans are re-read


# floor of the corner-run bar (title-block corner: right 45%, bottom 15%); the bar is also half the sheets' median
CORNER_MIN_RUNS = 4


# a text layer shorter than this on a scanned page (image-covered, or outlined line art) is a markup overlay, not the
# drawing's text
THIN_LAYER_CHARS = 400


TRIVIAL_TEXT_CHARS = 60  # a text layer shorter than this on an image-covered page counts as no text layer


OUTLINED_MIN_PATHS = 200  # line-art paths that make a text-less page a drawing (lettering as outlines), not a blank


OCR_CONF_CAP = 0.6  # a fact derived from OCR text never claims more than this


MIN_RUN_CONF = 0.5  # drop recognitions the engine itself doubts


OCR_MAX_PX = 9000  # longest edge of the raster handed to the detector
