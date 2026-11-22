"""A small drafting kit on top of PyMuPDF: the symbols a structural drawing is made of.

`generate.py` uses it to draw the example sets, and the tests use it to build one-page drawings that
trigger a single parser rule. Every symbol is drawn the way a CAD plot writes it into a PDF: text as
separate runs with a font size and a direction, lines as stroked paths with a width, circles as
closed curves. Those three things are all the reader ever looks at.

Coordinates are PDF points with the origin at the top-left corner of the sheet, y down. Angles are in
degrees, counter-clockwise as seen on the sheet (90 reads from the bottom up).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import pymupdf

FONT = "helv"
BOLD = "hebo"

HAIR = 0.35  # dimension, leader, grid and table lines
MEDIUM = 0.7  # outlines of plates and symbols
HEAVY = 1.6  # members and the sheet frame

PT_PER_MM = 72 / 25.4

Point = tuple[float, float]


def text_width(text: str, size: float, font: str = FONT) -> float:
    return pymupdf.get_text_length(text, fontname=font, fontsize=size)


def paper(length_mm: float, scale: float) -> float:
    """Length on paper, in points, of a real length drawn at 1:`scale`."""
    return length_mm / scale * PT_PER_MM


def wrap(text: str, size: float, width: float, font: str = FONT) -> list[str]:
    """Break `text` into lines no wider than `width` points."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and text_width(trial, size, font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + [current] if current else lines


class Canvas:
    """One sheet being drawn."""

    def __init__(self, page: pymupdf.Page):
        self.page = page
        self.width = page.rect.width
        self.height = page.rect.height

    # ---- primitives --------------------------------------------------------------------------
    def line(self, p1: Point, p2: Point, width: float = HAIR, dashes: str | None = None) -> None:
        shape = self.page.new_shape()
        shape.draw_line(p1, p2)
        shape.finish(width=width, dashes=dashes, closePath=False)
        shape.commit()

    def polyline(self, points: Sequence[Point], width: float = HAIR, close: bool = False) -> None:
        """Consecutive points joined by separate straight segments."""
        pairs = list(zip(points, points[1:], strict=False))
        if close:
            pairs.append((points[-1], points[0]))
        for a, b in pairs:
            self.line(a, b, width)

    def rect(self, x0: float, y0: float, x1: float, y1: float, width: float = HAIR) -> None:
        self.polyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], width, close=True)

    def filled_rect(self, x0: float, y0: float, x1: float, y1: float, grey: float = 0.0) -> None:
        shape = self.page.new_shape()
        shape.draw_rect(pymupdf.Rect(x0, y0, x1, y1))
        shape.finish(width=0, color=None, fill=(grey, grey, grey))
        shape.commit()

    def circle(self, centre: Point, radius: float, width: float = HAIR) -> None:
        shape = self.page.new_shape()
        shape.draw_circle(centre, radius)
        shape.finish(width=width, closePath=False)
        shape.commit()

    def text(
        self,
        x: float,
        y: float,
        text: str,
        size: float = 7,
        align: str = "left",
        angle: float = 0,
        font: str = FONT,
    ) -> None:
        """Write one run. (`x`, `y`) is the baseline point the text is aligned to: its start for
        "left", its middle for "center", its end for "right"."""
        ux, uy = math.cos(math.radians(angle)), -math.sin(math.radians(angle))
        shift = {"left": 0.0, "center": 0.5, "right": 1.0}[align] * text_width(text, size, font)
        start = pymupdf.Point(x - shift * ux, y - shift * uy)
        morph = (start, pymupdf.Matrix(angle)) if angle else None
        self.page.insert_text(start, text, fontsize=size, fontname=font, morph=morph)

    # ---- dimensions --------------------------------------------------------------------------
    def dimension(self, p1: Point, p2: Point, offset: float, label: str | None = None, size: float = 6.5) -> None:
        """A dimension between two points: extension lines, a dimension line `offset` points to the
        left of the direction p1 -> p2, a tick at each end, and the value centred above the line.

        The value is written along the line, so a vertical dimension reads from the bottom up when
        p1 is the lower point. With no `label` nothing is written (a dimension the tests leave bare).
        """
        length = math.dist(p1, p2)
        ux, uy = (p2[0] - p1[0]) / length, (p2[1] - p1[1]) / length
        nx, ny = uy, -ux  # left of the direction of travel, y down
        a = (p1[0] + nx * offset, p1[1] + ny * offset)
        b = (p2[0] + nx * offset, p2[1] + ny * offset)
        sign = 1 if offset >= 0 else -1
        for origin, end in ((p1, a), (p2, b)):
            self.line(
                (origin[0] + nx * 3 * sign, origin[1] + ny * 3 * sign), (end[0] + nx * 3 * sign, end[1] + ny * 3 * sign)
            )
        self.line(a, b)
        for end in (a, b):  # 45 degree ticks, shorter than any line the reader takes for a dimension line
            self.line((end[0] - 2, end[1] + 2), (end[0] + 2, end[1] - 2), MEDIUM)
        if label is None:
            return
        angle = math.degrees(math.atan2(-uy, ux))
        gap = 0.45 * size  # clear of the line: the value sits above it, not in it
        up_x, up_y = -math.sin(math.radians(angle)), -math.cos(math.radians(angle))
        mid = ((a[0] + b[0]) / 2 + up_x * gap, (a[1] + b[1]) / 2 + up_y * gap)
        self.text(mid[0], mid[1], label, size, "center", angle)

    # ---- symbols -----------------------------------------------------------------------------
    def grid_bubble(self, centre: Point, name: str, radius: float = 12, size: float = 10) -> None:
        """A grid bubble: a full circle with the grid name centred in it."""
        self.circle(centre, radius)
        self.text(centre[0], centre[1] + 0.36 * size, name, size, "center")

    def grid_line(self, p1: Point, p2: Point) -> None:
        self.line(p1, p2, HAIR, dashes="[9 2 2 2] 0")

    def callout(self, centre: Point, number: str, sheet: str, radius: float = 13, size: float = 6.5) -> None:
        """A detail or section callout: a circle split by a horizontal line, the detail number over
        the number of the sheet the detail is drawn on."""
        self.circle(centre, radius)
        self.line((centre[0] - radius, centre[1]), (centre[0] + radius, centre[1]))
        self.text(centre[0], centre[1] - 0.28 * size, number, size, "center")
        self.text(centre[0], centre[1] + 1.02 * size, sheet, size, "center")

    def leader(self, start: Point, end: Point) -> None:
        self.line(start, end)

    def level_marker(self, x: float, y: float, name: str, value: str, run: float = 0, size: float = 7) -> None:
        """An elevation marker at level `y`: the level name over its value, right-aligned at `x`,
        and a datum target to the right. `run` points of level line are drawn to the left."""
        name_width = max(text_width(name, size), text_width(value, size))
        self.line((x - name_width - 6 - run, y), (x + 22, y))
        self.text(x, y - 0.42 * size, name, size, "right")
        self.text(x, y + 0.78 * size, value, size, "right")
        cx, r = x + 13, 5.5
        self.circle((cx, y), r)
        for start, sweep in ((0, 90), (180, 90)):  # two opposite quadrants filled
            shape = self.page.new_shape()
            a0 = math.radians(start)
            shape.draw_sector((cx, y), (cx + r * math.cos(a0), y - r * math.sin(a0)), sweep)
            shape.finish(width=0, color=None, fill=(0, 0, 0))
            shape.commit()

    def view_title(
        self,
        x: float,
        y: float,
        title: str,
        scale: str,
        number: str = "",
        sheet: str = "",
        length: float = 220,
        size: float = 10,
    ) -> None:
        """A view title: the view number in a bubble (over the sheet number when `sheet` is given),
        the title on a line, the scale under it. (`x`, `y`) is the left end of the title's baseline."""
        if number and sheet:
            self.callout((x - 16, y + 2), number, sheet, radius=13, size=6)
        elif number:
            self.circle((x - 14, y - 2), 8)
            self.text(x - 14, y + 1, number, 8, "center")
        self.text(x, y, title, size, font=BOLD)
        self.line((x - (3 if number else 0), y + 2), (x + length, y + 2), MEDIUM)
        self.text(x, y + size, scale, 0.7 * size)

    def fillet_weld(
        self,
        joint: Point,
        elbow: Point,
        weld_size: str,
        both_sides: bool = False,
        typical: bool = False,
        leg: float = 8.5,
        text_size: float = 6.5,
    ) -> None:
        """A fillet weld symbol: a leader from the joint to the reference line, the weld triangle
        hanging under the line (arrow side; `both_sides` adds one above), the leg size left of it."""
        end = (elbow[0] + 46, elbow[1])
        self.line(joint, elbow)
        self.line(elbow, end)
        foot = (elbow[0] + 18, elbow[1])
        for direction in (1, -1) if both_sides else (1,):
            apex = (foot[0], foot[1] + direction * leg)
            far = (foot[0] + leg, foot[1])
            self.line(foot, apex)
            self.line(foot, far)
            self.line(apex, far)
        self.text(foot[0] - 2, foot[1] + leg - 1.2, weld_size, text_size, "right")
        if typical:
            self.text(end[0] + 3, end[1] + 0.3 * text_size, "TYP.", text_size)

    # ---- text blocks -------------------------------------------------------------------------
    def notes(
        self,
        x: float,
        y: float,
        heading: str,
        items: Sequence[str],
        width: float = 300,
        size: float = 7,
        numbered: bool = True,
    ) -> float:
        """A note block: an underlined-style heading ending in a colon, then numbered items with a
        hanging indent, wrapped to `width`. Returns the y below the block."""
        self.text(x, y, heading, size + 2, font=BOLD)
        y += 1.7 * size
        for n, item in enumerate(items, 1):
            indent = 16 if numbered else 0
            if numbered:
                self.text(x + 2, y, f"{n}.", size)
            for line in wrap(item, size, width - indent):
                self.text(x + indent, y, line, size)
                y += 1.25 * size
            y += 0.45 * size
        return y + 0.8 * size

    def table(
        self,
        x: float,
        y: float,
        column_widths: Sequence[float],
        rows: Sequence[Sequence[str]],
        row_height: float = 14,
        size: float = 7,
    ) -> float:
        """A ruled table. The first row is the header. Cell text is left-aligned. Returns the y below it."""
        total = sum(column_widths)
        for i in range(len(rows) + 1):
            self.line((x, y + i * row_height), (x + total, y + i * row_height), MEDIUM if i in (0, 1) else HAIR)
        edge = x
        for w in [0, *column_widths]:
            edge += w
            self.line((edge, y), (edge, y + len(rows) * row_height))
        for i, row in enumerate(rows):
            cell_x = x
            for cell, w in zip(row, column_widths, strict=True):
                if cell:
                    self.text(
                        cell_x + 4,
                        y + i * row_height + 0.5 * row_height + 0.36 * size,
                        cell,
                        size,
                        font=BOLD if i == 0 else FONT,
                    )
                cell_x += w
        return y + len(rows) * row_height


# ---- the sheet frame and title block ---------------------------------------------------------

MARGIN = 18
STRIP = 108  # height of the title strip along the bottom edge


def title_block(
    c: Canvas,
    *,
    client: str,
    project: Sequence[str],
    address: str,
    fields: dict[str, str],
    revisions: Sequence[tuple[str, str, str]],
    title: Sequence[str],
    number: str,
    footer: str = "SYNTHETIC EXAMPLE - NOT FOR CONSTRUCTION",
) -> None:
    """The sheet frame and a bottom title strip with labelled cells.

    From left to right: client and project, the revision table (REV / DESCRIPTION / DATE, oldest row
    first), six fields in two rows with each label above its value, the drawing title, the drawing
    number. `fields` maps a label ("PROJECT NO.", "DATE", "SCALE", "DRAWN BY", ...) to its value, at
    most six, filled row by row.
    """
    w, h = c.width, c.height
    top, bottom, left, right = h - MARGIN - STRIP, h - MARGIN, MARGIN, w - MARGIN
    c.rect(left, MARGIN, right, bottom, HEAVY)
    c.line((left, top), (right, top), HEAVY)
    span = right - left
    x_rev, x_fields, x_title, x_number = (left + f * span for f in (0.263, 0.49, 0.717, 0.902))
    for x in (x_rev, x_fields, x_title, x_number):
        c.line((x, top), (x, bottom), MEDIUM)

    label = 5.5
    c.text(left + 6, top + 8, "CLIENT", label)
    c.text(left + 6, top + 20, client, 8)
    c.text(left + 6, top + 34, "PROJECT", label)
    for i, line in enumerate(project):
        c.text(left + 6, top + 53 + 18 * i, line, 15, font=BOLD)
    c.text(left + 6, top + 53 + 18 * len(project) - 3, address, 7)

    rev_cols = (x_rev + 6, x_rev + 34, x_fields - 62)
    for x, head in zip(rev_cols, ("REV", "DESCRIPTION", "DATE"), strict=True):
        c.text(x, top + 14, head, 6, font=BOLD)
    c.line((x_rev, top + 18), (x_fields, top + 18))
    for i, row in enumerate(revisions):
        y = top + 28 + 10 * i
        for x, cell in zip(rev_cols, row, strict=True):
            c.text(x, y, cell, 6.5)
        c.line((x_rev, y + 3), (x_fields, y + 3))

    cell_w = (x_title - x_fields) / 3
    c.line((x_fields, top + STRIP / 2), (x_title, top + STRIP / 2))
    for k in (1, 2):
        c.line((x_fields + k * cell_w, top), (x_fields + k * cell_w, bottom))
    for k, (name, value) in enumerate(fields.items()):
        cx = x_fields + (k % 3) * cell_w + 6
        cy = top + (k // 3) * STRIP / 2
        c.text(cx, cy + 8, name, label)
        c.text(cx, cy + 24, value, 8)

    c.text(x_title + 6, top + 8, "DRAWING TITLE", label)
    for i, line in enumerate(title):
        c.text(x_title + 6, top + 34 + 18 * i, line, 15, font=BOLD)
    c.text(x_title + 6, bottom - 6, footer, label)

    c.text(x_number + 6, top + 8, "DRAWING NO.", label)
    c.text((x_number + right) / 2, top + 42, number, 20, "center", font=BOLD)


def new_sheet(doc: pymupdf.Document, width: float = 1224, height: float = 792) -> Canvas:
    """A new landscape sheet (11 x 17 in by default) at the end of `doc`."""
    return Canvas(doc.new_page(width=width, height=height))


def plot_rotated(doc: pymupdf.Document, source: pymupdf.Document, page_number: int = 0) -> None:
    """Append page `page_number` of `source` to `doc` the way many plotters write a landscape sheet:
    a portrait page whose content is turned a quarter turn, with a /Rotate entry that turns it back
    for display. The sheet looks the same on screen; its stored coordinates do not."""
    src = source[page_number]
    page = doc.new_page(width=src.rect.height, height=src.rect.width)
    page.show_pdf_page(page.rect, source, page_number, rotate=90)
    page.set_rotation(90)


def rasterise(source: pymupdf.Document, page_number: int, dpi: int = 200, seed: int = 7) -> pymupdf.Document:
    """A one-page PDF holding only a picture of the sheet, roughed up like an office scan: grey
    paper, a slight skew, soft edges and speckle. There is no text layer, so the reader has to OCR it."""
    import io
    import random

    from PIL import Image, ImageFilter

    src = source[page_number]
    pix = src.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    img = img.rotate(0.25, resample=Image.BICUBIC, fillcolor=255).filter(ImageFilter.GaussianBlur(0.6))
    img = Image.eval(img, lambda v: min(255, int(18 + 0.9 * v)))  # ink is dark grey, paper is off-white
    rng = random.Random(seed)
    px = img.load()
    for _ in range(img.width * img.height // 900):  # speckle
        px[rng.randrange(img.width), rng.randrange(img.height)] = rng.randrange(90, 200)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=72)
    out = pymupdf.open()
    page = out.new_page(width=src.rect.width, height=src.rect.height)
    page.insert_image(page.rect, stream=buffer.getvalue())
    return out


def save(doc: pymupdf.Document, path: str, title: str) -> None:
    """Write `doc` with neutral metadata and no timestamps or random ids, so the same script always
    produces the same file."""
    doc.set_metadata(
        {
            "title": title,
            "author": "",
            "subject": "Synthetic example drawing",
            "keywords": "",
            "creator": "structural-drawing-reader examples/generate.py",
            "producer": "PyMuPDF",
            "creationDate": "",
            "modDate": "",
        }
    )
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
