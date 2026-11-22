"""Page rendering resolution."""

from __future__ import annotations

RENDER_DPI = 150


MAX_RENDER_PX = 4000  # cap on a rendered page's longest edge, in pixels


def render_dpi_for(width_pt: float, height_pt: float, dpi: int = RENDER_DPI) -> float:
    """The DPI to render a page at so its longest edge never exceeds MAX_RENDER_PX.

    Large-format sheets (ARCH-E/A0-class) at a flat RENDER_DPI produce 25-50MP raw
    pixmaps; nothing downstream needs that (the providers downsize to 1600px wide, the
    Streamlit viewer scales to container width) so capping the render itself avoids
    the memory footprint with no loss of anything actually used.
    """
    return min(dpi, MAX_RENDER_PX * 72 / max(width_pt, height_pt))
