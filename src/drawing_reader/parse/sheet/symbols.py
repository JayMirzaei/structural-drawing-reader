"""Drafting symbols: grid bubbles, detail callouts, elevation markers and view titles."""

from __future__ import annotations

import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.dimension_values import RE_NUMBER
from drawing_reader.parse.layout import is_horizontal, same_row, x_overlap
from drawing_reader.parse.note_text import RE_ITEM_NO
from drawing_reader.parse.scale import RE_SCALE
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.parse.sheet_numbers import RE_SHEET_NO, sheet_ref_matches


class SymbolsMixin(SheetParserBase):
    """Reads the symbols that tie a drawing together, and assigns each fact to the view it sits in."""

    def parse_grids_callouts_elevations(self) -> None:
        """Conventions: grid bubble = full circle (Ø 25–50 pt) with a 1–3 char label centred; detail callout =
        number over a sheet id (split circle); elevation marker = name with a level value directly below,
        next to a small target circle. View title = '<n>  TITLE' with a scale '1 : N' directly below."""
        horiz = [r for r in self.body if is_horizontal(r)]
        # A section/detail "cut" convention numbers the same view twice on one sheet: once as a
        # small standalone circled marker in the plan (no label beside it -- just the number,
        # geometrically identical to a real grid bubble) and once beside the view's own "SECTION"/
        # "DETAIL"/"ELEVATION" heading elsewhere on the sheet. The heading instance identifies the
        # number as belonging to this convention, not a real grid -- so exclude that value's *every*
        # occurrence on this sheet, not just the one sitting next to the heading (such a sheet may have
        # no real column-line grids at all).
        section_marker_values = {
            r.text.strip().upper()
            for r in horiz
            for o in horiz
            if o is not r
            and o.text.strip().upper() in ("SECTION", "DETAIL", "ELEVATION")
            and same_row(r, o, tol=1.5 * r.size)
            and 0 <= o.bbox[0] - r.bbox[2] < 60
        }
        # The number in the top half of a callout bubble sits in a full circle like a grid name does. What
        # tells them apart is the sheet id written directly under it, so those numbers are found first.
        callout_numbers = {
            o.id
            for r in horiz
            if RE_SHEET_NO.match(r.text.strip().replace(" ", "")) and re.search(r"[.\-]", r.text)
            for o in self._detail_numbers_above(r, horiz)[:1]
        }
        for r in horiz:
            if r.id in self.used:
                continue
            t = r.text.strip()
            # grid bubble: a *round* full circle (thin stroke, width ~= height) with a short label;
            # a thick-stroke or elongated "circle" is some other graphic (a schedule's highlighted
            # cell, a leader-line terminator) that happens to enclose text, not a drafted bubble —
            # and a 3-digit number that isn't paired with a letter reads as a dimension, not a grid.
            if (
                len(t) <= 3
                and re.match(r"^(?:[A-Z]{1,2}\d{0,2}|\d{1,2})$", t)
                and t
                and t.upper() not in section_marker_values
                and r.id not in callout_numbers
            ):
                # Bubble diameter is judged against the label's own size, not absolute points: a 36x24 in sheet
                # printed on letter paper has 11 pt bubbles around 5.5 pt labels. the 60 pt ceiling and 20 pt floor
                # stay for big sheets; small text lowers the floor to 2x its size (never below 8 pt).
                c = self._circle_containing(r, min(20, max(8, 2.0 * r.size)), 60)
                if c and c.arcs >= 3 and c.diameter > 1.2 * (r.bbox[2] - r.bbox[0]):
                    cw, ch = c.bbox[2] - c.bbox[0], c.bbox[3] - c.bbox[1]
                    if c.width <= 3.0 and abs(cw - ch) <= 0.15 * max(cw, ch):
                        self._add("grid", t, c.bbox, t, conf=0.85, name=t)
                        self.used.add(r.id)
                        continue
            # callout: sheet id with a detail number directly above. Requires a dot/dash separator
            # ("S.1", "S01-02"). A bare sheet-number-shaped run with no separator ("S6") is a real
            # convention too, but accepting it here produced false positives on multi-discipline sets:
            # two-letter marks ("SW4", a shear-wall mark) and, even with a single-letter prefix, door
            # numbers ("D123"), light-fixture marks ("L201") and other letter-plus-digit marks that are
            # not sheet references. Known limit: reading those needs a cross-sheet pass that checks
            # the candidate against every sheet's resolved number (as the `target_in_set` pass in
            # `build_index` does), not a shape guess made before the sheet numbers are known.
            if RE_SHEET_NO.match(t.replace(" ", "")) and re.search(r"[.\-]", t):
                # Gap between the detail number and the sheet id is judged against the font size, not a fixed 2 pt of
                # slack: on a reduced print (2.4 pt text) the 1.5 pt gap failed `gap + 2 <= size`.
                above = self._detail_numbers_above(r, horiz)
                if above:
                    a = above[0]
                    bbox = (min(a.bbox[0], r.bbox[0]) - 8, a.bbox[1] - 4, max(a.bbox[2], r.bbox[2]) + 8, r.bbox[3] + 4)
                    self._add(
                        "callout",
                        f"{a.text}/{t}",
                        bbox,
                        f"{a.text} / {t}",
                        conf=0.85,
                        detail=a.text,
                        target_sheet=t.replace(" ", ""),
                    )
                    self.used.update({r.id, a.id})
                    continue
            # view title with scale below
            m_scale = RE_SCALE.match(t)
            if m_scale:
                scale_val = m_scale.group(1)
                title = None
                above = [
                    o
                    for o in horiz
                    if o is not r
                    and 0 <= r.bbox[1] - o.bbox[3] + 3 <= 1.2 * r.size
                    and x_overlap(r.bbox, o.bbox) > 0
                    and o.size >= r.size
                ]
                if above:
                    title = max(above, key=lambda o: o.size)
                if title:
                    num = [
                        o
                        for o in horiz
                        if o is not title
                        and RE_ITEM_NO.match(o.text)
                        and same_row(title, o, 8)
                        and 0 < title.bbox[0] - o.bbox[2] < 40
                    ]
                    # multi-line titles: another title-sized line directly above
                    extra = [
                        o
                        for o in horiz
                        if o is not title
                        and o.size == title.size
                        and 0 <= title.bbox[1] - o.bbox[3] + 3 <= 0.8 * title.size
                        and x_overlap(title.bbox, o.bbox) > 0
                    ]
                    full = (extra[0].text + " " if extra else "") + title.text
                    bbox = (
                        min(o.bbox[0] for o in [title, r] + num + extra),
                        min(o.bbox[1] for o in [title, r] + num + extra),
                        max(o.bbox[2] for o in [title, r] + num + extra),
                        r.bbox[3],
                    )
                    self._add(
                        "view",
                        full,
                        bbox,
                        f"{num[0].text + ' ' if num else ''}{full} {t}",
                        conf=0.85,
                        title=full,
                        number=num[0].text if num else "",
                        scale=scale_val,
                    )
                    self.used.update({r.id, title.id} | {o.id for o in num + extra})
                    continue
            # elevation marker: name above a numeric value, right-aligned, small full circle beside
            if RE_NUMBER.match(t):
                # The name needs a letter and >= 2 alphanumerics ("T1", "ROOF"): a stray "-" / "x" above a number is a
                # callout bubble's remnant, not a level name (accepting it produced "-: 6 mm" elevations that
                # hijacked other questions).
                def _name_candidates(lo, hi, align):
                    return [
                        o
                        for o in horiz
                        if o is not r
                        and not RE_NUMBER.match(o.text)
                        and not RE_ITEM_NO.match(o.text)
                        and re.search(r"[A-Za-z]", o.text)
                        and len(re.sub(r"[^A-Za-z0-9]", "", o.text)) >= 2
                        and lo <= r.bbox[1] - o.bbox[3] <= hi
                        and abs(o.bbox[2] - r.bbox[2]) < align
                        and o.size == r.size
                    ]

                def _marker_beside(name):
                    # the circle-cross target beside the pair; its size is judged against the text, not absolute points
                    return any(
                        min(10, max(5, 1.6 * r.size)) <= c.diameter <= max(30, 8 * r.size)
                        and c.arcs >= 3
                        and abs(c.center[1] - (name.bbox[3] + r.bbox[1]) / 2) < 1.5 * r.size
                        and 0 < c.bbox[0] - r.bbox[2] < 40
                        for c in self.s.circles
                    )

                # Strict geometry (large prints) stands on its own; the relaxed, size-scaled gap needed for reduced
                # prints (3.6 pt text, 1.9 pt gap) is accepted only when the marker circle is there too -- without it
                # the same loose geometry matched door numbers, "IN mm" and "TOLERANCE, TYP." on other sheets.
                above = _name_candidates(-3.0, 0.6 * r.size - 3, 4)
                near_circle = bool(above) and _marker_beside(above[0])
                if not above:
                    above = [
                        o
                        for o in _name_candidates(
                            -min(3.0, 0.5 * r.size), max(0.6 * r.size - 3, 0.65 * r.size), max(4, r.size)
                        )
                        if _marker_beside(o)
                    ]
                    near_circle = bool(above)
                if above:
                    name = above[0]
                    bbox = (min(name.bbox[0], r.bbox[0]), name.bbox[1], max(name.bbox[2], r.bbox[2]), r.bbox[3])
                    self._add(
                        "elevation",
                        t,
                        bbox,
                        f"{name.text} {t}",
                        unit="mm",
                        conf=0.85 if near_circle else 0.6,
                        name=name.text,
                        has_marker=near_circle,
                    )
                    self.used.update({r.id, name.id})
                    continue

    @staticmethod
    def _detail_numbers_above(sheet_id: TextRun, horiz: list[TextRun]) -> list[TextRun]:
        """Runs that read as the detail number of a callout whose sheet id is `sheet_id`: a short
        number directly above it. The gap is judged against the font size, not a fixed 2 pt of slack:
        on a reduced print (2.4 pt text) a 1.5 pt gap is a normal one."""
        return [
            o
            for o in horiz
            if o is not sheet_id
            and RE_ITEM_NO.match(o.text)
            and -min(2.0, 0.5 * sheet_id.size) <= sheet_id.bbox[1] - o.bbox[3] <= 1.0 * sheet_id.size
            and x_overlap(sheet_id.bbox, o.bbox) > 0
        ]

    def merge_view_number_markers(self) -> None:
        """Convention: a detail-callout-shaped bubble (number over the sheet's *own* number) placed
        directly left of a view title, on the same row, is that view's number, not a cross-reference
        -- the callout branch above runs first and has no way to tell the two apart on shape alone.
        The view may already carry that number (the bubble's top half was close enough to the title to
        be read with it); the bubble is then only dropped from the callouts."""
        for v in [f for f in self.facts if f.kind == "view"]:
            number = v.attrs.get("number")
            cands = [
                c
                for c in self.facts
                if c.kind == "callout"
                and sheet_ref_matches(c.attrs.get("target_sheet", ""), self.meta.number)
                and min(c.bbox[3], v.bbox[3]) - max(c.bbox[1], v.bbox[1]) > 0
                and (
                    (c.attrs.get("detail") == number and c.bbox[0] <= v.bbox[0] + 12 and v.bbox[0] <= c.bbox[2])
                    if number
                    else 0 <= v.bbox[0] - c.bbox[2] <= 60
                )
            ]
            if len(cands) != 1:
                continue
            c = cands[0]
            if not number:
                v.attrs["number"] = c.attrs["detail"]
                v.source_text = f"{c.attrs['detail']} {v.source_text}"
            v.bbox = (
                min(v.bbox[0], c.bbox[0]),
                min(v.bbox[1], c.bbox[1]),
                max(v.bbox[2], c.bbox[2]),
                max(v.bbox[3], c.bbox[3]),
            )
            self.facts.remove(c)

    def assign_views(self) -> None:
        """Each fact gets the nearest view title located below it (view titles sit under their drawing)."""
        views = [f for f in self.facts if f.kind == "view"]
        if not views:
            return
        for f in self.facts:
            if f.kind in ("view", "sheet", "titleblock", "revision"):
                continue
            cx, cy = (f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2
            best, bd = None, 1e9
            for v in views:
                vx, vy = (v.bbox[0] + v.bbox[2]) / 2, v.bbox[1]
                if vy < cy - 10:  # title above the fact -> not its view
                    continue
                d = ((cx - vx) ** 2 + (cy - vy) ** 2) ** 0.5
                if d < bd:
                    best, bd = v, d
            if best:
                f.view = best.attrs.get("title")
