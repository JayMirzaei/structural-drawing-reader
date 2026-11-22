"""Revision tables: three readers for the layouts revision histories are drawn in."""

from __future__ import annotations

import re

from drawing_reader.parse.layout import is_horizontal, same_row
from drawing_reader.parse.revision_text import (
    RE_DATE,
    RE_DATEISH,
    RE_LEADING_DATE,
    RE_REV_CODE,
    RE_REV_DATE_HDR,
    RE_REV_DESC_HDR,
    RE_REV_NUM_HDR,
    REV_DESC_HEADERS,
    REV_NUM_HEADERS,
    reads_like_a_note,
)
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.parse.titleblock_fields import is_label_text


class RevisionsMixin(SheetParserBase):
    """Reads revision rows from a labelled table, a banded table or rows led by a dotted revision code."""

    def parse_revision_header_table(self, variants: bool = False) -> None:
        """Convention: some templates place the revision history as a labelled table (column
        headers 'REV' next to 'ISSUED FOR' or 'DESCRIPTION', optionally 'DATE') rather than a bare
        numbered list — and some put that table in the sheet's top margin rather than the bottom
        title strip, unlike `parse_titleblock`'s revision-row scan above. Detect it by its header
        row wherever it sits, then read each row below by column x-position."""
        horiz = [r for r in self.s.runs if is_horizontal(r)]
        for rev_hdr in horiz:
            hdr_text = rev_hdr.text.strip().rstrip(":")
            if not (RE_REV_NUM_HDR.match(hdr_text) if variants else hdr_text.upper() == "REV"):
                continue
            tol = max(4.0, 0.6 * rev_hdr.size) if variants else 4.0
            row = [o for o in horiz if o is not rev_hdr and same_row(rev_hdr, o, tol=tol)]
            if variants:  # several tables can share a row: take the headers nearest to this one
                row = sorted(
                    (o for o in row if abs(o.bbox[0] - rev_hdr.bbox[0]) <= 600),
                    key=lambda o: abs(o.bbox[0] - rev_hdr.bbox[0]),
                )
            desc_hdr = next(
                (
                    o
                    for o in row
                    if (
                        RE_REV_DESC_HDR.match(o.text.strip().rstrip(":"))
                        if variants
                        else o.text.strip().upper() in ("ISSUED FOR", "DESCRIPTION")
                    )
                ),
                None,
            )
            if not desc_hdr:
                continue
            date_hdr = next(
                (
                    o
                    for o in row
                    if (
                        RE_REV_DATE_HDR.match(o.text.strip().rstrip(":"))
                        if variants
                        else o.text.strip().upper() == "DATE"
                    )
                ),
                None,
            )
            if variants and date_hdr is None and not re.match(r"REV", hdr_text, re.I):
                continue  # a bare "NO." / "#" header is a revision table only with a date column beside it
            cols = sorted([c for c in (date_hdr, desc_hdr, rev_hdr) if c], key=lambda c: c.bbox[0])
            names = {id(c): ("date" if c is date_hdr else "description" if c is desc_hdr else "number") for c in cols}

            def col_range(i):
                x0 = cols[i].bbox[0] - 10 if i == 0 else (cols[i - 1].bbox[2] + cols[i].bbox[0]) / 2
                x1 = cols[i].bbox[2] + 200 if i == len(cols) - 1 else (cols[i].bbox[2] + cols[i + 1].bbox[0]) / 2
                return x0, x1

            ranges = [(names[id(c)], *col_range(i)) for i, c in enumerate(cols)]
            header_top, header_bottom = min(c.bbox[1] for c in cols), max(c.bbox[3] for c in cols)
            max_extent = max(100.0, 0.2 * self.s.height)
            in_cols = [r for r in horiz if r not in cols and any(x0 <= r.center[0] <= x1 for _, x0, x1 in ranges)]

            def read_rows(candidates, above_dir=False):
                rows: dict[int, list] = {}
                # a row is a cluster of centres within half a text height (a fixed 6 pt bucket splits cells set 1 pt
                # apart)
                if variants:
                    n = -1
                    last = None
                    for r in sorted(candidates, key=lambda r: r.center[1]):
                        if last is None or r.center[1] - last > 0.5 * rev_hdr.size:
                            n += 1
                        rows.setdefault(n, []).append(r)
                        last = r.center[1]
                else:
                    for r in candidates:
                        rows.setdefault(round(r.bbox[1] / 6), []).append(r)
                out = []
                for key in sorted(rows):
                    cells = rows[key]
                    vals = {}
                    for name, x0, x1 in ranges:
                        # the last column reaches 200 pt past its header and can take in a neighbouring title-block
                        # field's label ("DRAWN BY") on the same row: a field label is never a revision cell
                        in_col = sorted(
                            (c for c in cells if x0 <= c.center[0] <= x1 and not is_label_text(c.text)),
                            key=lambda c: c.bbox[0],
                        )
                        if in_col:
                            if name == "date" and variants:
                                # the column may also take in a neighbouring column's initials ("AB 14/05/31"): the date
                                # cell alone is the date
                                dc = [c for c in in_col if re.search(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{8}", c.text)]
                                in_col = dc or in_col
                            vals[name] = " ".join(c.text for c in in_col)
                            if name == "number" and variants:
                                ids = [
                                    c
                                    for c in in_col
                                    if re.fullmatch(r"[A-Za-z0-9]{1,3}", c.text.strip())
                                    # the id is the leftmost short cell; a word of the description may reach into the
                                    # column
                                ]
                                if ids:
                                    vals[name] = ids[0].text
                    num = vals.get("number", "").strip()
                    if not num or len(num) > 4 or not re.match(r"^[A-Za-z0-9]+$", num):
                        continue
                    if variants:
                        # wider headers: a revision id is one or two digits or a letter, and the row has a date or a
                        # real description
                        desc_v, date_v = vals.get("description", ""), vals.get("date", "")
                        dated = bool(
                            re.fullmatch(
                                r"\d{4}[-/.]?\d{2}[-/.]?\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}",
                                date_v.strip(),
                            )
                        )
                        if not (
                            re.fullmatch(r"\d{1,2}|[A-Z]\d?", num)
                            and (
                                dated
                                or re.search(
                                    r"\b(?:ISSUED?|FOR|REVISED?|REVISION|PERMIT|TENDER|CONSTRUCTION|APPROVAL|FABRICAT\w*|BID|ADDENDUM|RECORD|REVIEW|DRAFT|TEMPLATE)\b",
                                    desc_v,
                                    re.I,
                                )
                            )
                        ):
                            continue
                    out.append((cells, vals, num))
                if variants:
                    # a revision table is a compact block: rows follow one another from the header, a gap ends it
                    near = sorted(
                        out,
                        key=lambda o: abs(min(c.bbox[1] for c in o[0]) - (header_top if above_dir else header_bottom)),
                    )
                    kept, last = [], header_bottom if not above_dir else header_top
                    for o in near:
                        y = min(c.bbox[1] for c in o[0])
                        if abs(y - last) > 6 * rev_hdr.size:
                            break
                        kept.append(o)
                        last = y
                    out = sorted(kept, key=lambda o: min(c.bbox[1] for c in o[0]))
                return out

            below = read_rows(
                [
                    r
                    for r in in_cols
                    if -(0.3 * rev_hdr.size if variants else 0.0) <= r.bbox[1] - header_bottom < max_extent
                ]
            )
            # the table can grow upward from a header set at its foot (newest row nearest the title block)
            above = (
                read_rows(
                    [
                        r
                        for r in in_cols
                        if -(0.3 * rev_hdr.size if variants else 0.0) <= header_top - r.bbox[3] < max_extent
                    ],
                    above_dir=True,
                )
                if not below
                else []
            )
            for cells, vals, num in below or above:
                desc, date = vals.get("description", ""), vals.get("date", "")
                if reads_like_a_note(desc):
                    continue
                bbox = (
                    min(c.bbox[0] for c in cells),
                    min(c.bbox[1] for c in cells),
                    max(c.bbox[2] for c in cells),
                    max(c.bbox[3] for c in cells),
                )
                self._add(
                    "revision",
                    f"Rev {num}: {desc}" + (f" ({date})" if date else ""),
                    bbox,
                    " ".join(c.text for c in cells),
                    conf=0.85,
                    number=num,
                    description=desc,
                    date=date,
                )
                self._rev_table_found = True
            if below or above or not variants:
                # one revision table per sheet; stop after the first header match (wider wording: the first with rows)
                return

    def parse_revision_rows_by_code(self) -> None:
        """Convention: a revision log whose rows lead with a dotted revision code ("0.A.0", "0.B.1") followed on the
        same row by a description and a date, with or without a header (a scan drops or garbles the header words).
        Last resort, after the header-based readers: the dotted code is distinctive enough to anchor a row by itself,
        and the row must carry a date and a description naming an issue purpose."""
        horiz = [r for r in self.s.runs if is_horizontal(r)]
        for code in horiz:
            if not RE_REV_CODE.match(code.text.strip()):
                continue
            row = [
                o
                for o in horiz
                if o is not code and same_row(code, o, tol=max(4.0, 0.5 * code.size)) and o.bbox[0] >= code.bbox[2] - 2
            ]
            row.sort(key=lambda o: o.bbox[0])
            dates = [
                o for o in row if RE_DATE.search(o.text) or re.fullmatch(r"\d{4}[-/.]\d{2}[-/.]\d{2}", o.text.strip())
            ]
            descs = [
                o
                for o in row
                if o not in dates
                and re.search(
                    r"\b(?:ISSUED?|FOR|REVISED?|REVISION|PERMIT|TENDER|CONSTRUCTION|APPROVAL|REVIEW|RECORD)\b",
                    o.text,
                    re.I,
                )
                and o.bbox[0] - code.bbox[2] <= 200
            ]
            if not dates or not descs:
                continue
            desc, date = descs[0].text, dates[0].text.strip()
            if reads_like_a_note(desc):
                continue
            cells = [code, descs[0], dates[0]]
            bbox = (
                min(c.bbox[0] for c in cells),
                min(c.bbox[1] for c in cells),
                max(c.bbox[2] for c in cells),
                max(c.bbox[3] for c in cells),
            )
            num = code.text.strip().upper().replace("O", "0")
            self._add(
                "revision",
                f"Rev {num}: {desc} ({date})",
                bbox,
                " ".join(c.text for c in cells),
                conf=0.8,
                number=num,
                description=desc,
                date=date,
            )
            self._rev_table_found = True

    def parse_revision_table_banded(self) -> None:
        """Convention: a labelled revision table whose header the older reader above cannot
        use -- the number header is "No."/"I/R" instead of "REV", the rows sit *above* a bottom header (newest on
        top) instead of below it, or a row's date/description wrap over several lines ("JUN 29" / "2020").
        Rows are bands opened by each number-column run and closed by the next one; every other run inside the
        table's x-range is a date cell if it is date-shaped, else description (a run that starts with a date and
        carries description words after it is split). Only runs when the older reader found no table, so tables
        that already parsed are untouched."""
        if self._rev_table_found:
            return
        horiz = [r for r in self.s.runs if is_horizontal(r)]
        for hdr in horiz:
            if hdr.text.strip().upper() not in REV_NUM_HEADERS:
                continue
            row = [o for o in horiz if o is not hdr and same_row(hdr, o, tol=4)]
            desc_hdr = next((o for o in row if o.text.strip().upper().rstrip(":") in REV_DESC_HEADERS), None)
            date_hdr = next((o for o in row if o.text.strip().upper().rstrip(":") == "DATE"), None)
            if not desc_hdr or (hdr.text.strip().upper() in {"NO", "NO.", "#"} and not date_hdr):
                continue
            x_lo, x_hi = hdr.bbox[0] - 12, desc_hdr.bbox[2] + 220
            # A "BY"/"DRAWN"/"APPR." column to the right of the description holds initials, not description words.
            by_hdr = next(
                (
                    o
                    for o in row
                    if o.text.strip().upper().rstrip(".:")
                    in {
                        "BY",
                        "DRAWN",
                        "DR",
                        "APPR",
                        "APPROVED",
                        "INIT",
                        "INITIALS",
                        "DWN",
                        "DRN",
                        "CHK",
                        "CHKD",
                        "DFTG",
                        "APP",
                        "SUPV",
                    }
                    and o.bbox[0] > desc_hdr.bbox[0]
                ),
                None,
            )
            by_x = by_hdr.bbox[0] - 6 if by_hdr else None
            if by_hdr is not None:
                x_hi = max(x_hi, by_hdr.bbox[2] + 10)
            extent = max(100.0, 0.2 * self.s.height)

            def numbers(side):
                out = []
                for r in horiz:
                    if (
                        r is hdr
                        or not (x_lo <= r.center[0] <= hdr.bbox[2] + 12)
                        or not re.fullmatch(r"\d{1,2}[A-Za-z]?|[A-Za-z]", r.text.strip())
                    ):
                        continue
                    dy = r.bbox[1] - hdr.bbox[3] if side == "below" else hdr.bbox[1] - r.bbox[3]
                    if -1 <= dy <= extent:
                        out.append(r)
                return sorted(out, key=lambda r: r.bbox[1])

            below, above = numbers("below"), numbers("above")
            nums, side = (below, "below") if len(below) >= len(above) else (above, "above")
            if not nums:
                continue
            ys = [n.bbox[1] - 2 for n in nums] + [
                (hdr.bbox[1] - 2) if side == "above" else (nums[-1].bbox[1] + 3.5 * nums[-1].size)
            ]
            rows = []
            for i, n in enumerate(nums):
                cells = [
                    r
                    for r in horiz
                    if r is not n
                    and ys[i] <= r.bbox[1] < ys[i + 1]
                    and x_lo <= r.center[0] <= x_hi
                    and not (
                        r.center[0] <= hdr.bbox[2] + 12 and re.fullmatch(r"\d{1,2}[A-Za-z]?|[A-Za-z]", r.text.strip())
                    )
                ]
                cells.sort(key=lambda r: (round(r.bbox[1] / 4), r.bbox[0]))
                # A band is a contiguous block of lines: stop at the first vertical gap > 1.8 line heights (without
                # it, the last row can be joined to a title line printed just below the table).
                by_cells = [c for c in cells if by_x is not None and c.center[0] >= by_x]
                cells = [c for c in cells if c not in by_cells]
                kept, prev_bottom = [], n.bbox[3]
                for c in cells:
                    if c.bbox[1] - prev_bottom > 1.8 * c.size:
                        break
                    kept.append(c)
                    prev_bottom = max(prev_bottom, c.bbox[3])
                cells = kept
                date_parts, desc_parts = [], []
                for c in cells:
                    t = c.text.strip()
                    if RE_DATEISH.match(t):
                        date_parts.append(t)
                    elif m := RE_LEADING_DATE.match(t):
                        date_parts.append(m.group(1))
                        desc_parts.append(m.group(2))
                    else:
                        desc_parts.append(t)
                rows.append(
                    (
                        n,
                        cells + by_cells,
                        " ".join(date_parts),
                        " ".join(desc_parts),
                        " ".join(c.text.strip() for c in by_cells),
                    )
                )
            # A revision table dates its issues: when no row carries a date, this was a different "No." table
            # (a numbered notes list, a schedule, a legend) and nothing is emitted.
            if not any(date for _, _, date, _, _ in rows):
                continue
            for n, cells, date, desc, by in rows:
                if not (date or desc):
                    continue
                if reads_like_a_note(desc):
                    continue  # a numbered sentence of the general notes under the table
                allr = [n] + cells
                bbox = (
                    min(r.bbox[0] for r in allr),
                    min(r.bbox[1] for r in allr),
                    max(r.bbox[2] for r in allr),
                    max(r.bbox[3] for r in allr),
                )
                num = n.text.strip()
                self._add(
                    "revision",
                    f"Rev {num}: {desc}" + (f" ({date})" if date else ""),
                    bbox,
                    " ".join(r.text for r in allr),
                    conf=0.8,
                    number=num,
                    description=desc,
                    date=date,
                    by=by,
                )
                self.used.update(r.id for r in allr)
                self._rev_table_found = True
            self.used.update({hdr.id, desc_hdr.id} | ({date_hdr.id} if date_hdr else set()))
            return
