"""Page rendering at ingestion: the pixel cap for large-format sheets, and the stored scale between
PDF points and image pixels."""

from __future__ import annotations

import pymupdf
import pytest
from PIL import Image

from drawing_reader.ingest import MAX_RENDER_PX, RENDER_DPI, ingest, render_dpi_for

LARGE = (3370, 2384)  # an A0 sheet, in points
SMALL = (1224, 792)  # a tabloid sheet, the size of the example set


def blank_pdf(path, size):
    doc = pymupdf.open()
    doc.new_page(width=size[0], height=size[1])
    doc.save(str(path))
    doc.close()
    return path


def rendered_width(sheet) -> int:
    with Image.open(sheet.image_path) as img:
        return img.width


def test_large_format_sheet_render_is_capped(tmp_path):
    """A large-format sheet at the flat render DPI would give an image of tens of megapixels. Its
    longest edge is capped, and the stored scale is the one of the image actually written."""
    sheet = ingest(blank_pdf(tmp_path / "large.pdf", LARGE), tmp_path / "cache").sheets[0]
    with Image.open(sheet.image_path) as img:
        assert max(img.size) <= MAX_RENDER_PX
    assert max(LARGE) / 72 * RENDER_DPI > MAX_RENDER_PX  # the cap was needed
    assert sheet.image_scale == pytest.approx(rendered_width(sheet) / LARGE[0], abs=1e-6)


def test_small_sheet_render_is_unaffected_by_the_cap(tmp_path):
    """A sheet well under the cap renders at the flat DPI, and the stored scale still comes from the
    image written (a few pixels of rounding must not drift from a fixed ratio)."""
    assert render_dpi_for(*SMALL) == RENDER_DPI
    sheet = ingest(blank_pdf(tmp_path / "small.pdf", SMALL), tmp_path / "cache").sheets[0]
    width = rendered_width(sheet)
    assert abs(width - SMALL[0] / 72 * RENDER_DPI) < 2
    assert sheet.image_scale == pytest.approx(width / SMALL[0])


def test_render_scale_is_the_same_after_a_cache_hit(tmp_path):
    """A second ingestion of the same file reuses the cached primitives and the image on disk. The
    scale must come out the same, not fall back to the flat DPI ratio."""
    pdf = blank_pdf(tmp_path / "large.pdf", LARGE)
    first = ingest(pdf, tmp_path / "cache").sheets[0]
    second = ingest(pdf, tmp_path / "cache").sheets[0]
    assert second.image_scale == first.image_scale
    assert second.image_scale < RENDER_DPI / 72
