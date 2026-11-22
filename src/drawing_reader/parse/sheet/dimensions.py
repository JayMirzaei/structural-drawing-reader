"""Dimensions: numbers that sit on a dimension line, with table cells kept out and chains checked."""

from __future__ import annotations

import re
from collections import Counter

from drawing_reader.ingest import Segment
from drawing_reader.parse.dimension_values import FOOT_MARK, RE_DIM_QUALIFIER, RE_DIM_UNITS_NOTE, dimension_value
from drawing_reader.parse.layout import is_horizontal, run_orientation
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.schema import Fact


class DimensionsMixin(SheetParserBase):
    """Reads dimension values and cross-checks them (chains that add up, scale measured from dimensions)."""

    def _table_runs(self) -> set[str]:
        """Convention: a schedule / point table / quantity table is a block of rows, each row three or more cells
        (text runs) on one baseline, at a steady row pitch, with the cells of one column lined up (same left edge,
        right edge or centre) from row to row. Numbers in such a block are cell contents -- the rules between the rows
        run parallel to them and are not dimension lines -- so they are not dimensions. A dimension chain is one row
        (or a few rows that do not line up), never four rows of aligned cells."""
        if getattr(self, "_tbl", None) is not None:
            return self._tbl
        runs = [r for r in self.body if is_horizontal(r) and r.text.strip()]
        self._tbl = set()
        if len(runs) < 12:
            return self._tbl
        hs = sorted(r.bbox[3] - r.bbox[1] for r in runs)
        h = hs[len(hs) // 2] or 1.0
        rows: list[list] = []
        for r in sorted(runs, key=lambda r: r.center[1]):
            if rows and abs(r.center[1] - rows[-1][0]) <= 0.5 * h:
                rows[-1][1].append(r)
            else:
                rows.append([r.center[1], [r]])
        rows = [(y, sorted(rs, key=lambda r: r.bbox[0])) for y, rs in rows]
        rows = [(y, rs) for y, rs in rows if len(rs) >= 3]
        tol = 0.6 * h
        hsegs = [
            ((min(g.p1[0], g.p2[0]), max(g.p1[0], g.p2[0])), (g.p1[1] + g.p2[1]) / 2)
            for g in self.s.segments
            if abs(g.p1[1] - g.p2[1]) <= 1.5 and abs(g.p1[0] - g.p2[0]) >= 3 * h
        ]
        band: list = []

        def close(band):
            if len(band) < 4:
                return
            cols = Counter()
            for _, rs in band:
                for r in rs:
                    for kind, v in (("l", r.bbox[0]), ("r", r.bbox[2]), ("c", r.center[0])):
                        cols[(kind, round(v / tol))] += 1

            def aligned(r):
                return any(
                    max(cols[(kind, q + d)] for d in (-1, 0, 1)) >= 3
                    for kind, q in (
                        ("l", round(r.bbox[0] / tol)),
                        ("r", round(r.bbox[2] / tol)),
                        ("c", round(r.center[0] / tol)),
                    )
                )

            members = [r for _, rs in band for r in rs]
            if sum(aligned(r) for r in members) < 0.6 * len(members):
                return
            if self.is_scan and len(hsegs) < 4 and len(band) >= 5:
                # a scan carries no line geometry to check the rules by: five or more rows of three-plus cells whose
                # columns line up are a table
                self._tbl.update(r.id for r in members if aligned(r))
                return
            # a table is ruled: a cell has a horizontal line above and below it (row lines), across its width -- a
            # dimension line runs along one side of its number only, and member marks that merely line up in an
            # elevation have no row lines at all
            pitch = (band[-1][0] - band[0][0]) / (len(band) - 1)
            lo, hi = 0.3 * h, 0.75 * pitch + 0.5 * h
            cells = []
            for i, (_y, rs) in enumerate(band):
                for r in rs:
                    cx, cy = r.center
                    ok = [g for g in hsegs if g[0][0] - tol <= cx <= g[0][1] + tol]
                    above = any(lo <= cy - g[1] <= hi for g in ok)
                    below = any(lo <= g[1] - cy <= hi for g in ok)
                    if (above and below) or ((above or below) and i in (0, len(band) - 1)):
                        cells.append(r)
            if len(cells) >= 0.5 * len(members):
                self._tbl.update(r.id for r in cells if aligned(r))

        for y, rs in rows:
            if band and y - band[-1][0] > 4 * h:
                close(band)
                band = []
            band.append((y, rs))
        close(band)
        # A grid of numbers (a point table, a coordinate list): a number with three or more cells on its row and five
        # or more numbers in its column at a steady pitch is a cell, whether or not the ruling was read.
        nums = [r for r in runs if re.fullmatch(r"[-+]?[\d,.]{2,}", r.text.strip())]
        by_row: dict[int, list] = {}
        for r in runs:
            by_row.setdefault(round(r.center[1] / (0.5 * h)), []).append(r)
        for r in nums:
            if r.id in self._tbl:
                continue
            k = round(r.center[1] / (0.5 * h))
            if (
                sum(
                    1
                    for q in (k - 1, k, k + 1)
                    for o in by_row.get(q, [])
                    if o is not r
                    and abs(o.center[1] - r.center[1]) <= 0.5 * h
                    and abs(o.center[0] - r.center[0]) <= 500
                )
                < 3
                or not self.is_scan
            ):
                continue
            # a table's cells line up to the pixel; a dimension string's numbers do not
            col = sorted(
                o.center[1]
                for o in nums
                if min(abs(o.center[0] - r.center[0]), abs(o.bbox[0] - r.bbox[0]), abs(o.bbox[2] - r.bbox[2]))
                <= 0.25 * h
            )
            if len(col) >= 5:
                gaps = [b - a for a, b in zip(col, col[1:], strict=False) if b - a > 0.5 * h]
                if len(gaps) >= 4:
                    med = sorted(gaps)[len(gaps) // 2]
                    if sum(1 for g in gaps if abs(g - med) <= 0.2 * med) >= 0.6 * len(gaps):
                        self._tbl.add(r.id)
        return self._tbl

    def parse_dimensions(self) -> None:
        """Convention: a dimension value is a bare number whose writing direction is parallel to a thin
        line running under/along it. Unit follows the sheet's general notes (mm assumed)."""
        note = RE_DIM_UNITS_NOTE.search(" ".join(r.text for r in self.s.runs if "DIMENSION" in r.text.upper()))
        default_unit = {"INCHES": "in", "FEET": "ft"}.get(note.group("u").upper(), "mm") if note else "mm"
        table = self._table_runs()
        # A detail tag: a number in a bubble ("44") whose drawing reference is printed beside it ("XYZ-00-015-44") --
        # the number is the tail of that reference, not a length; so is the "-44" a leader drops on the reference
        # itself.
        refs = [
            (r, m.group(1))
            for r in self.body
            if is_horizontal(r) and (m := re.search(r"[A-Za-z]{2,5}-\d{2,}-\d{2,}-(\d{1,3})$", r.text.strip()))
        ]
        tag_nums: set[str] = set()
        if refs:
            for r in self.body:
                t = r.text.strip().lstrip("-")
                if re.fullmatch(r"\d{1,3}", t) and any(
                    t == tail
                    and abs(r.center[0] - q.center[0]) <= 6 * q.size + 0.5 * (q.bbox[2] - q.bbox[0])
                    and abs(r.center[1] - q.center[1]) <= 4 * q.size
                    for q, tail in refs
                ):
                    tag_nums.add(r.id)
        table = table | tag_nums
        words = [o for o in self.body if is_horizontal(o) and re.search(r"[A-Za-z]{2,}", o.text)]

        def sentence(r) -> bool:
            """A number set inside a line of words ("1 1/2 x 22 Ga STEEL DECK"): words close on both sides of it on its
            own baseline."""
            if not is_horizontal(r):
                return False
            gap = 1.2 * r.size
            left = any(
                o is not r and abs(o.center[1] - r.center[1]) <= 0.5 * r.size and 0 <= r.bbox[0] - o.bbox[2] <= gap
                for o in words
            )
            right = [
                o
                for o in words
                if o is not r and abs(o.center[1] - r.center[1]) <= 0.5 * r.size and 0 <= o.bbox[0] - r.bbox[2] <= gap
            ]
            # a number that opens a line of words ("40" DEEP OWSJ", "20 Ga STEEL DECK") is a note, unless the word is a
            # dimension's own qualifier
            # next to another number: one of a string of dimensions
            in_chain = any(
                o is not r
                and abs(o.center[1] - r.center[1]) <= 0.5 * r.size
                and 0 <= r.bbox[0] - o.bbox[2] <= 2.5 * gap
                and re.fullmatch(r"[\d.,'\"\-\s/]+", o.text.strip())
                for o in self.body
            )
            opens = not in_chain and any(not RE_DIM_QUALIFIER.match(o.text.strip()) for o in right)
            return (left and bool(right)) or opens

        in_table = {tuple(r.bbox) for r in self.body if r.id in table}
        for f in self.facts:
            if f.kind == "label" and tuple(f.bbox) in in_table:
                f.attrs["in_table"] = True  # a schedule entry (an MTO line), not a member drawn on the plan
        # The bottom band is taken for the title block, but a plan can run into it (the title block is a right-hand
        # strip that was not found):
        # feet-inch values there are dimensions of the plan; plain numbers in the band stay with the title block
        band_ftin = [
            r
            for r in self.tb
            if re.fullmatch(
                rf"\d{{1,3}}{FOOT_MARK}\s?-?\s?\d{{1,2}}(?:\s?\d{{1,2}}/\d{{1,2}})?[\"”″*°]?", r.text.strip()
            )
            and is_horizontal(r)
        ]
        for r in self.body + band_ftin:
            dv = None if (r.id in self.used or r.id in table) else dimension_value(r.text, default_unit)
            if dv is None:
                continue
            # A number written with a leading minus ("-159" in an oval, an elevation offset, "-8\"" cut from "6'-8\"",
            # "-01" from a drawing reference) is no length: a dimension is never negative, and a fragment that starts
            # at a dash is the end of something longer.
            if re.match(r"^[-\u2212\u2013]\s?\d", r.text.strip()):
                continue
            # A number set inside a small circle is a bubble (detail, section, keynote, grid), not a length.
            if (
                (c := self._circle_containing(r, min_d=4, max_d=60))
                and c.diameter <= 4.5 * r.size
                and len(r.text.strip()) <= 3
            ):
                continue
            # "L/240", "1/360": the number after a slash on its own baseline is a ratio in a note, not a length.
            if any(
                o is not r
                and abs(o.center[1] - r.center[1]) <= 0.5 * r.size
                and 0 <= r.bbox[0] - o.bbox[2] <= 0.8 * r.size
                and o.text.rstrip().endswith("/")
                for o in self.body
            ):
                continue
            # Text above 14 pt is usually a grid label or title, but detail sheets drawn at large zoom (15-20 pt
            # numbers on CLT/foundation details) put real dimensions there too. Big text is accepted only on the
            # strict test below: a hairline running under the whole number, tightly offset, much longer than the
            # number. An OCR box is padded: its height is ~1.4x the lettering, so a scan's "size" is scaled down here,
            # and a lone digit on a scan (a scale-bar tick, a grid mark) is not a dimension.
            fs = r.size * (0.7 if self.is_scan else 1.0)
            if self.is_scan and len(r.text.strip()) < 2:
                continue
            big = fs > 14
            if big and not (len(r.text.strip()) >= 2 and fs <= 30):
                continue
            cx, cy = r.center
            dx, dy = r.dir
            text_len = abs((r.bbox[2] - r.bbox[0]) * dx) + abs((r.bbox[3] - r.bbox[1]) * dy)

            def nearest(max_width, strict):
                """Closest parallel line under/along the text. `strict` (big text, thick lines) additionally needs the
                number to sit within the line's extent, close to it, and the line to be much longer than the number."""
                best = None
                for seg in self.s.segments:
                    if seg.length < 8 or seg.width > max_width:
                        continue
                    sx, sy = seg.p2[0] - seg.p1[0], seg.p2[1] - seg.p1[1]
                    L = seg.length
                    if abs((sx * dx + sy * dy) / L) < 0.97:
                        continue
                    d = abs((sx * (cy - seg.p1[1]) - sy * (cx - seg.p1[0])) / L)
                    tproj = ((cx - seg.p1[0]) * sx + (cy - seg.p1[1]) * sy) / (L * L)
                    if strict:
                        if not (d < 0.9 * fs and 0.0 <= tproj <= 1.0 and L >= 4 * max(text_len, 1.0)):
                            continue
                    elif not (d < 1.6 * fs and -0.2 <= tproj <= 1.2):
                        continue
                    # A string of dimensions is drawn as collinear pieces, all at the same distance from the
                    # number: the piece the number sits over is its line, not a neighbour it overhangs.
                    over = 0.0 <= tproj <= 1.0
                    if best is not None and abs(d - best[0]) <= 0.25 and over != best[2]:
                        closer = over
                    else:
                        closer = best is None or d < best[0]
                    if closer:
                        best = (d, seg, over)
                return best

            def inline_gap(max_width):
                """Dimension text set inline in a gap of its own line: pieces of the line end on either side of the
                number, on its axis. The two pieces join into one line (the number sits between them, with room for
                the text, not far apart)."""
                lo_seg = hi_seg = None
                for seg in self.s.segments:
                    if seg.length < 8 or seg.width > max_width:
                        continue
                    sx, sy = seg.p2[0] - seg.p1[0], seg.p2[1] - seg.p1[1]
                    L = seg.length
                    if abs((sx * dx + sy * dy) / L) < 0.97:
                        continue
                    if abs((sx * (cy - seg.p1[1]) - sy * (cx - seg.p1[0])) / L) > 0.7 * fs:
                        continue  # not on the text's own axis
                    a = (seg.p1[0] - cx) * dx + (seg.p1[1] - cy) * dy
                    b = (seg.p2[0] - cx) * dx + (seg.p2[1] - cy) * dy
                    lo, hi = min(a, b), max(a, b)
                    if -3 * text_len <= hi <= 0.6 * text_len and (lo_seg is None or hi > lo_seg[0]):
                        lo_seg = (hi, seg, lo)
                    if -0.6 * text_len <= lo <= 3 * text_len and (hi_seg is None or lo < hi_seg[0]):
                        hi_seg = (lo, seg, hi)
                if lo_seg is None or hi_seg is None:
                    # unidirectional dimensioning: the text stays upright on a line running through it at right angles
                    # (a horizontal number in a gap of a vertical line); pieces end above and below the number
                    if abs(dx) < 0.99 and abs(dy) < 0.99:
                        return None
                    vx, vy = -dy, dx
                    up = down = None
                    through = None
                    for seg in self.s.segments:
                        if seg.length > 0 and seg.length >= 4 * fs and seg.width <= max_width:
                            sx, sy = seg.p2[0] - seg.p1[0], seg.p2[1] - seg.p1[1]
                            if abs((sx * vx + sy * vy) / seg.length) >= 0.97:
                                off = abs((seg.p1[0] - cx) * dx + (seg.p1[1] - cy) * dy)
                                a = (seg.p1[0] - cx) * vx + (seg.p1[1] - cy) * vy
                                b = (seg.p2[0] - cx) * vx + (seg.p2[1] - cy) * vy
                                if (
                                    off <= 0.35 * text_len
                                    and min(a, b) <= 0.0 <= max(a, b)
                                    and (through is None or off < through[0])
                                ):
                                    # the number is written over an unbroken line running through it
                                    through = (
                                        off,
                                        seg,
                                    )
                    if through is not None:
                        return (0.0, through[1])
                    for seg in self.s.segments:
                        if seg.length < 8 or seg.width > max_width:
                            continue
                        sx, sy = seg.p2[0] - seg.p1[0], seg.p2[1] - seg.p1[1]
                        L = seg.length
                        if abs((sx * vx + sy * vy) / L) < 0.97:
                            continue  # the piece must run along the perpendicular
                        if abs((seg.p1[0] - cx) * dx + (seg.p1[1] - cy) * dy) > 0.5 * text_len:
                            continue  # and pass through the number's width
                        a = (seg.p1[0] - cx) * vx + (seg.p1[1] - cy) * vy
                        b = (seg.p2[0] - cx) * vx + (seg.p2[1] - cy) * vy
                        lo, hi = min(a, b), max(a, b)
                        if -4 * text_len <= hi <= 0.6 * fs and (up is None or hi > up[0]):
                            up = (hi, seg, lo)
                        if -0.6 * fs <= lo <= 4 * text_len and (down is None or lo < down[0]):
                            down = (lo, seg, hi)
                    if up is None or down is None:
                        return None
                    gap_v = down[0] - up[0]
                    if not (0.3 * fs <= gap_v <= 3 * fs + 0.5 * text_len):
                        return None
                    pts = [up[1].p1, up[1].p2, down[1].p1, down[1].p2]
                    pts.sort(key=lambda q: (q[0] - cx) * vx + (q[1] - cy) * vy)
                    return (0.0, Segment(p1=pts[0], p2=pts[-1], width=max(up[1].width, down[1].width), dashed=False))
                gap = hi_seg[0] - lo_seg[0]
                if not (0.8 * text_len <= gap <= 2.6 * text_len + 2 * fs):
                    return None
                a_seg, b_seg = lo_seg[1], hi_seg[1]
                pts = [a_seg.p1, a_seg.p2, b_seg.p1, b_seg.p2]
                pts.sort(key=lambda q: (q[0] - cx) * dx + (q[1] - cy) * dy)
                return (0.0, Segment(p1=pts[0], p2=pts[-1], width=max(a_seg.width, b_seg.width), dashed=False))

            thin = 6.0 if self.is_scan else 1.0  # a raster line is a few pixels wide, a vector hairline under 1 pt
            # first: a number set in a gap of its own line takes the whole line, not one piece of it
            best = inline_gap(thin)
            inline = best is not None
            if best is None:
                best = nearest(thin, strict=big)
            if best is None and not big:
                best = nearest(5.0, strict=True)  # thick-line templates (heavy-line layouts): second pass only
            if best and not sentence(r):
                conf = 0.8
                line_length_pt = round(best[1].length, 1)
                extra = {"inline": True} if inline else {}
                value = dv[0]
                if value > 0 and line_length_pt > 0:
                    # a dimension's value is the true (paper) length of the thin line it sits on;
                    # paper mm = pt * 25.4/72, so this ratio is the drawing's scale as measured by
                    # this one dimension -- a cross-check against the view title (assign_scale_consensus).
                    extra["scale_ratio"] = round(value / (line_length_pt * 25.4 / 72), 1)
                self._add(
                    "dimension",
                    r.text,
                    r,
                    r.text,
                    unit=dv[1],
                    conf=conf,
                    orientation=run_orientation(r),
                    dim_kind=dv[2],
                    value_mm=round(dv[0], 2),
                    line=[best[1].p1, best[1].p2],
                    line_length_pt=line_length_pt,
                    **extra,
                )
                self.used.add(r.id)
            elif dv[1] == "ft-in" and re.match(rf"^\d{{1,3}}{FOOT_MARK}", r.text.strip()) and not sentence(r):
                # "40'-0"" is a dimension whatever line it sits on: a scan's raster line detection can miss a thin or
                # broken line
                self._add(
                    "dimension",
                    r.text,
                    r,
                    r.text,
                    unit=dv[1],
                    conf=0.5,
                    orientation=run_orientation(r),
                    dim_kind=dv[2],
                    value_mm=round(dv[0], 2),
                    no_line=True,
                )
                self.used.add(r.id)
            elif dv[2] != "linear":
                # a radius / diameter label sits on a leader, not along a parallel line: kept, with lower confidence and
                # no line
                self._add(
                    "dimension",
                    r.text,
                    r,
                    r.text,
                    unit=dv[1],
                    conf=0.6,
                    orientation=run_orientation(r),
                    dim_kind=dv[2],
                    value_mm=round(dv[0], 2),
                )
                self.used.add(r.id)
        self._check_dimension_chains()

    def _check_dimension_chains(self) -> None:
        """Convention: a string of dimensions along one line adds up to an overall dimension on a parallel line ("5000
        5000 6000 ... = 49000"). Dimensions on one line axis (within 3 pt; a raster line is cut into pieces at ticks)
        form a chain; when a chain of two or more sums to another dimension's value on the sheet (within 0.3%), the
        members get chain_ok and the total gets chain_total with its parts' ids as links -- an independent check that
        the numbers were read right and sit on the right line."""
        dims = [
            f
            for f in self.facts
            if f.kind == "dimension" and f.attrs.get("line") and f.attrs.get("dim_kind") == "linear"
        ]
        chains: list[tuple[bool, float, list[Fact]]] = []  # (horizontal, axis coordinate, members)
        for f in dims:
            (x1, y1), (x2, y2) = f.attrs["line"]
            h = abs(y1 - y2) <= abs(x1 - x2)
            ax = (y1 + y2) / 2 if h else (x1 + x2) / 2
            for c in chains:
                if c[0] == h and abs(c[1] - ax) <= 3:
                    c[2].append(f)
                    break
            else:
                chains.append((h, ax, [f]))
        for h, _ax, members in chains:
            if len(members) < 2:
                continue
            total = sum(f.attrs["value_mm"] for f in members)
            for h2, _ax2, others in chains:
                if h2 != h or others is members:
                    continue
                hit = next((t for t in others if abs(t.attrs["value_mm"] - total) <= max(1.0, 0.003 * total)), None)
                if hit:
                    for f in members:
                        f.attrs["chain_ok"] = True
                    hit.attrs["chain_total"] = True
                    hit.links = [f.id for f in members]
                    break

    def assign_scale_consensus(self) -> None:
        """Convention: a dimension's printed value is the true (paper) length of the thin line it
        sits on, so `scale_ratio` (set in parse_dimensions; paper mm = pt * 25.4/72) is a measured
        drawing scale from that one dimension. A view's own dimensions should mostly agree on one
        such ratio, so the largest tight cluster (members within +/-3% of each other) is a cheap
        cross-check against the titled '1 : N' scale, and also gives a measured scale for NTS /
        'As indicated' views that have no numeric title at all."""
        views = [f for f in self.facts if f.kind == "view"]
        if not views:
            return
        dims = [f for f in self.facts if f.kind == "dimension"]
        for v in views:
            title = v.attrs.get("title")
            ratios = [d.attrs["scale_ratio"] for d in dims if d.view == title and "scale_ratio" in d.attrs]
            n = len(ratios)
            if n == 0:
                continue
            titled_n = None
            m = re.match(r"^1\s?:\s?(\d{1,4})$", (v.attrs.get("scale") or "").strip())
            if m:
                titled_n = float(m.group(1))
            best_k, best_candidates = 0, []
            for r in ratios:
                k = sum(1 for r2 in ratios if abs(r2 - r) <= 0.03 * r)
                if k > best_k:
                    best_k, best_candidates = k, [r]
                elif k == best_k:
                    best_candidates.append(r)
            if best_k < 2:
                continue
            if len(best_candidates) == 1:
                best = best_candidates[0]
            elif titled_n is not None:
                best = min(best_candidates, key=lambda r: abs(r - titled_n))
            else:
                continue  # a genuine tie with no titled scale to break it -- leave this view alone
            v.attrs["scale_measured"] = f"1 : {round(best)}"
            v.attrs["scale_support"] = f"{best_k}/{n}"
        # A sheet printed fit-to-page is uniformly smaller than drawn (for example ~3.3x), so every view's measured
        # scale is the titled one times the same factor. When at least 3 views on the sheet are measured and their
        # measured/titled factors agree (within 15% of the median, median > 1.3), record that factor so the
        # cross-check can say "agrees after reduction" instead of warning on every correctly scaled view.
        factors = []
        for v in views:
            m = re.match(r"^1\s?:\s?(\d{1,4})$", (v.attrs.get("scale") or "").strip())
            sm = re.match(r"^1 : (\d+)$", v.attrs.get("scale_measured") or "")
            if m and sm and int(m.group(1)) > 0:
                factors.append((v, int(sm.group(1)) / int(m.group(1))))
        if len(factors) >= 3:
            ordered = sorted(f for _, f in factors)
            med = ordered[len(ordered) // 2]
            agree = [v for v, f in factors if abs(f - med) <= 0.15 * med]
            if med > 1.3 and len(agree) >= 3 and len(agree) / len(factors) >= 0.6:
                for v in views:
                    v.attrs["print_reduction"] = round(med, 1)
