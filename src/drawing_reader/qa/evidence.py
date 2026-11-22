"""Evidence rendering: draw the cited facts' boxes on the sheet image."""

from __future__ import annotations

from PIL import Image, ImageDraw

from drawing_reader.schema import Index

KIND_COLORS = {
    "label": (220, 40, 40),
    "dimension": (40, 120, 220),
    "elevation": (150, 60, 200),
    "grid": (0, 150, 90),
    "callout": (230, 130, 0),
    "view": (90, 90, 90),
    "note": (0, 140, 160),
    "material": (0, 140, 160),
    "reference": (200, 0, 120),
    "revision": (120, 120, 0),
    "titleblock": (120, 120, 0),
    "sheet": (120, 120, 0),
    "angle": (200, 90, 40),
    "weld": (170, 0, 200),
    "text": (160, 160, 160),
}


def render_sheet(idx: Index, sheet_number: str, show_kinds: set[str], highlight_ids: list[str]) -> Image.Image | None:
    meta = idx.sheet_by_number(sheet_number)
    if not meta or not meta.image_path:
        return None
    img = Image.open(meta.image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    k = meta.image_scale
    for f in idx.facts:
        if f.sheet != sheet_number or f.kind not in show_kinds:
            continue
        x0, y0, x1, y1 = [v * k for v in f.bbox]
        draw.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=KIND_COLORS.get(f.kind, (0, 0, 0)), width=2)
    hl = set(highlight_ids)
    for f in idx.facts:
        if f.sheet != sheet_number or f.id not in hl:
            continue
        x0, y0, x1, y1 = [v * k for v in f.bbox]
        pad = 10
        for w in (0, 3):
            draw.rectangle([x0 - pad - w, y0 - pad - w, x1 + pad + w, y1 + pad + w], outline=(255, 0, 0), width=4)
    return img
