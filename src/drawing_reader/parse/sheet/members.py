"""Member labels, angle annotations and fillet-weld symbols."""

from __future__ import annotations

import math
import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.dimension_values import RE_NUMBER
from drawing_reader.parse.layout import is_horizontal, run_orientation
from drawing_reader.parse.members import FAMILY_NAMES, RE_ANGLE, RE_SECTION, RE_TYP, parse_extended_member
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.parse.sheet_numbers import RE_SHEET_NO


class MembersMixin(SheetParserBase):
    """Reads member designations placed along members, and weld symbols drawn as line geometry."""

    def parse_labels(self) -> None:
        """Convention: member designations (W310X39, HSS152X152X9.5, PL 10) are placed along the
        member, so the label's rotation tells the member orientation. For PL (plate) labels specifically:
        a bare 'PL t' is a thickness callout, while 'PL AxBxC' gives plan size plus thickness -- ordering
        varies across drafters (thickness last or first), but the thickness is always the smallest of the
        numbers since a plate is thinner than its plan dimensions, so that's how thickness/plan are split
        out into attrs regardless of which position it was written in."""
        for r in self.body:
            if r.id in self.used:
                continue
            t = r.text.replace("×", "X").strip()
            # stray point OCR puts after the prefix or the X: "W.310X52", "W200X.36"
            t = re.sub(r"(?<=[Xx])\.(?=\d)", "", re.sub(r"^([A-Za-z]{1,3})\.(?=\d)", r"\1", t))
            m = RE_SECTION.match(t)
            # a two-letter prefix (PL12.7, WT12.5) is a member, whatever else it resembles
            sheet_like = bool(RE_SHEET_NO.match(t)) and not t[1:2].isalpha()
            if m and any(ch.isdigit() for ch in t) and not sheet_like:
                fam = m.group("fam").upper()
                strict_ok = not (
                    (
                        fam == "S" and "." in t and "X" not in m.group("dims").upper()
                    )  # S.2-style sheet ids are not sections
                    or "=" in t
                    or (fam in ("L", "C", "MC", "S", "M", "W", "HS", "HA") and "X" not in m.group("dims").upper())
                )
                #   'C1 & C2 = 6.4mm' is a note, not a channel; 'MC1'/'MC2' (a masonry-column schedule mark) is not
                # a channel either. A text the strict reader rejects still gets the extended reader below ("L2 1/2 X 2
                # 1/2 x 1/4").
            else:
                strict_ok = False
            if strict_ok:
                plate_attrs = {}
                if fam == "PL":
                    parts = re.split(r"\s?X\s?", m.group("dims").strip(), flags=re.I)
                    nums = [float(p) for p in parts]
                    thin = nums.index(min(nums))
                    plate_attrs["thickness"] = parts[thin]
                    plate_attrs["plan"] = "X".join(parts[:thin] + parts[thin + 1 :])
                section = (fam + m.group("dims")).replace(" ", "")
                if fam in ("HS", "HA"):
                    plate_attrs["designation_prefix"] = fam
                    fam = "HSS"
                if m.group("count"):
                    plate_attrs["count"] = int(m.group("count"))
                self._add(
                    "label",
                    t,
                    r,
                    r.text,
                    conf=0.9,
                    family=fam,
                    family_name=FAMILY_NAMES.get(fam, fam),
                    orientation=run_orientation(r),
                    angle=r.angle,
                    section=section,
                    **plate_attrs,
                )
                self.used.add(r.id)
                continue
            ext = parse_extended_member(t) if not RE_ANGLE.match(t) else None
            if ext and not (sheet_like and not ext[2].get("partial")) and len(t) <= 60:
                fam, section, attrs = ext
                self._add(
                    "label",
                    t,
                    r,
                    r.text,
                    conf=0.6 if attrs.get("partial") else 0.85,
                    family=fam,
                    family_name=FAMILY_NAMES.get(fam, fam),
                    orientation=run_orientation(r),
                    angle=r.angle,
                    section=section,
                    form="extended",
                    **attrs,
                )
                self.used.add(r.id)
                continue
            if RE_ANGLE.match(t):
                self._add(
                    "angle",
                    t.replace(" ", "").rstrip("°"),
                    r,
                    r.text,
                    unit="deg",
                    conf=0.85,
                    orientation=run_orientation(r),
                    angle=r.angle,
                )
                self.used.add(r.id)

    def parse_welds(self) -> None:
        """Convention: a fillet weld symbol is a thin (width<=1.0) horizontal reference line carrying
        a right-triangle glyph -- a vertical segment of length L (6-30 pt) with one endpoint on the
        line, and a diagonal from its other endpoint back to a point on the line L away (all
        tolerances <=1.5 pt). The size is a horizontal bare-number run (RE_NUMBER, size <= max(14, 2.5 L)) whose
        right edge is 0-1.5*L left of the vertical leg and whose centre-y lies within that triangle's
        vertical span; a "TYP." run on the same row within 100 pt right of the line's end marks it
        typical. One weld fact per reference line (not per triangle): a triangle drawn below the line
        (y-down) is the "arrow" side, one drawn above is the "other" side, both together is "both".
        A symbol with no size run produces no fact. Runs this early (before parse_notes/
        parse_dimensions) so a weld-size number or its "TYP." tag is never misfiled as a numbered
        note item or a dimension string riding the same thin reference line."""

        def close(a, b, tol=1.5):
            return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

        thin = [seg for seg in self.s.segments if seg.width <= 1.0]
        # legs as short as 10 pt occur
        vertical = [seg for seg in thin if abs(seg.p2[0] - seg.p1[0]) <= 1.5 and 6 <= seg.length <= 30]
        horiz = [seg for seg in thin if abs(seg.p2[1] - seg.p1[1]) <= 1.5 and seg.length >= 8]
        diag = [
            seg
            for seg in thin
            if abs(seg.p2[0] - seg.p1[0]) >= 8
            and abs(seg.p2[1] - seg.p1[1]) >= 8
            and abs(abs(seg.p2[0] - seg.p1[0]) - abs(seg.p2[1] - seg.p1[1])) <= 2.0
        ]

        groups: dict[tuple[int, int, int, int], list[dict]] = {}
        for v in vertical:
            L = v.length
            for p_on, apex in ((v.p1, v.p2), (v.p2, v.p1)):
                for h in horiz:
                    if close(h.p1, p_on):
                        p_far = h.p2
                    elif close(h.p2, p_on):
                        p_far = h.p1
                    else:
                        continue
                    if abs(math.dist(p_on, p_far) - L) > 1.5:
                        continue
                    if any(
                        (close(d.p1, apex) and close(d.p2, p_far)) or (close(d.p2, apex) and close(d.p1, p_far))
                        for d in diag
                    ):
                        key = (round(p_on[0]), round(p_on[1]), round(p_far[0]), round(p_far[1]))
                        groups.setdefault(key, []).append({"p_on": p_on, "p_far": p_far, "apex": apex, "L": L})
                        break
                else:
                    # Reference line passing *through* the glyph (for example a 50 pt line with two triangles on a
                    # shared vertical stem) instead of ending at its corner: take the base corner from the diagonal
                    # that leaves the apex, and require one horizontal line covering both the stem foot and that
                    # corner.
                    for d in diag:
                        far = d.p2 if close(d.p1, apex) else d.p1 if close(d.p2, apex) else None
                        if far is None or abs(far[1] - p_on[1]) > 1.5 or abs(abs(far[0] - p_on[0]) - L) > 1.5:
                            continue
                        lo, hi = sorted((p_on[0], far[0]))
                        if any(
                            abs(h.p1[1] - p_on[1]) <= 1.5
                            and min(h.p1[0], h.p2[0]) - 1.5 <= lo
                            and hi <= max(h.p1[0], h.p2[0]) + 1.5
                            for h in horiz
                        ):
                            # keyed by the stem foot so both triangles of one glyph land in the same group
                            key = (round(p_on[0]), round(p_on[1]), 0, 0)
                            groups.setdefault(key, []).append({"p_on": p_on, "p_far": far, "apex": apex, "L": L})
                            break

        # per-triangle check below: <= 2.5x its leg
        number_runs = [
            r
            for r in self.body
            if r.id not in self.used
            and is_horizontal(r)
            and RE_NUMBER.match(r.text.strip())
            and not r.text.strip().startswith("-")
            and r.size <= 30
        ]
        typ_runs = [r for r in self.body if r.id not in self.used and is_horizontal(r) and RE_TYP.match(r.text.strip())]
        claimed: set[str] = set()

        for tris in groups.values():
            sides = set()
            matched: list[TextRun] = []
            boxes = []
            for t in tris:
                p_on, p_far, apex, L = t["p_on"], t["p_far"], t["apex"], t["L"]
                sides.add("below" if apex[1] > p_on[1] else "above")
                span_lo, span_hi = sorted((p_on[1], apex[1]))
                for r in number_runs:
                    if r.id in claimed or r.size > max(14.0, 2.5 * L):
                        continue
                    if 0 <= p_on[0] - r.bbox[2] <= 1.5 * L and span_lo <= r.center[1] <= span_hi:
                        matched.append(r)
                        claimed.add(r.id)
                xs = (p_on[0], p_far[0], apex[0])
                ys = (p_on[1], p_far[1], apex[1])
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
            if not matched:
                continue
            matched.sort(key=lambda r: r.bbox[1])
            line_end_x = max(x for t in tris for x in (t["p_on"][0], t["p_far"][0]))
            line_y = tris[0]["p_on"][1]
            typ_hit = next(
                (r for r in typ_runs if abs(r.center[1] - line_y) <= 3 and 0 <= r.bbox[0] - line_end_x <= 100), None
            )
            all_boxes = boxes + [r.bbox for r in matched]
            bbox = (
                min(b[0] for b in all_boxes),
                min(b[1] for b in all_boxes),
                max(b[2] for b in all_boxes),
                max(b[3] for b in all_boxes),
            )
            side = "both" if len(sides) == 2 else ("arrow" if "below" in sides else "other")
            self._add(
                "weld",
                matched[0].text.strip(),
                bbox,
                " ".join(r.text for r in matched),
                unit="mm",
                conf=0.85,
                sides=side,
                typical=typ_hit is not None,
                line=[tris[0]["p_on"], tris[0]["p_far"]],
            )
            for r in matched:
                self.used.add(r.id)
            if typ_hit:
                self.used.add(typ_hit.id)
