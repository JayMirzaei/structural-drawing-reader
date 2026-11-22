"""Shared state and helpers of the per-sheet parser."""

from __future__ import annotations

from collections import Counter

from drawing_reader.ingest import Sheet, TextRun
from drawing_reader.parse.layout import bottom_band_y, is_horizontal, same_row, titleblock_runs, x_overlap
from drawing_reader.schema import Fact, SheetMeta


class SheetParserBase:
    """State of one sheet's parse, and the small geometric lookups every rule group uses.

    The rule groups live in mixin classes (one module per topic) that all extend this base;
    `SheetParser` combines them and fixes the order in which they run (`SheetParser.run`).

    State shared between rule groups, and who writes it (everything else is read-only after `__init__`):

    * `facts`, `used`: every rule appends facts and adds the ids of the runs it consumed to `used`;
      a later rule skips used runs. This is why the run order matters.
    * `meta`: the title-block rules (titleblock.py, titles.py) set number, title, fields and scale;
      `run` stamps the final sheet number into every fact id at the end.
    * `tb`, `body`: set here; `parse_titleblock` may widen them once on a scan (`_widen_titleblock`)
      before any later rule reads them.
    * `_rev_table_found`: set by the revision-table readers (revisions.py), which run before
      `parse_titleblock`; when True its own row-by-row revision pass is skipped.
    * `_title_label_stack`: reset by `parse_titleblock`, set by `_title_from_label` (titles.py) to
      the lines of a title read under its label, then used by `parse_titleblock` to cite them.
    * `_tbl`: the table-cell run ids, computed once by the dimension rules (dimensions.py).
    * `repeated`: texts repeated across the set, set by `build_index` before `run`.
    * `title_src`: which title rule won (diagnostics only)."""

    def __init__(self, sheet: Sheet):
        self.s = sheet
        self.page = sheet.index + 1
        self.band = bottom_band_y(sheet)
        self.facts: list[Fact] = []
        self.meta = SheetMeta(
            page=self.page,
            number=f"P{self.page}",
            image_path=sheet.image_path,
            image_scale=sheet.image_scale,
            width=sheet.width,
            height=sheet.height,
            text=sheet.full_text,
        )
        self._n = Counter()
        self.tb = titleblock_runs(sheet)
        tb_ids = {id(r) for r in self.tb}
        self.body = [r for r in sheet.runs if id(r) not in tb_ids]
        self.used: set[str] = set()  # run ids already consumed by a parser
        self._rev_table_found = False
        self._tbl: set[str] | None = None  # table-cell run ids, computed once by `_table_runs`
        self._title_label_stack: list[TextRun] | None = None  # the lines of a title read under its label
        self.repeated: set[str] = set()  # `_repeated_block_texts`, set by build_index
        # text read by OCR (a confident OCR run also rounds to conf 1.0, so test the page)
        self.is_scan = any(r.conf < 1.0 for r in sheet.runs)
        self.title_src = ""  # which rule set the sheet title (diagnostics only)

    def _fid(self, kind: str) -> str:
        self._n[kind] += 1
        return f"@.{kind}.{self._n[kind]:03d}"

    def _add(self, kind, value, run_or_bbox, source, unit=None, conf=0.8, view=None, **attrs) -> Fact:
        bbox = run_or_bbox.bbox if isinstance(run_or_bbox, TextRun) else tuple(run_or_bbox)
        f = Fact(
            id=self._fid(kind),
            kind=kind,
            value=str(value),
            unit=unit,
            sheet=self.meta.number,
            page=self.page,
            view=view,
            bbox=bbox,
            source_text=source,
            confidence=conf,
            attrs=attrs,
        )
        self.facts.append(f)
        return f

    def _right_of(self, r: TextRun, pool: list[TextRun], max_gap=260) -> TextRun | None:
        cands = [
            o
            for o in pool
            if o is not r and same_row(r, o) and o.bbox[0] >= r.bbox[2] - 2 and o.bbox[0] - r.bbox[2] < max_gap
        ]
        return min(cands, key=lambda o: o.bbox[0]) if cands else None

    def _below(self, r: TextRun, pool: list[TextRun], max_gap_factor=1.2) -> TextRun | None:
        cands = [
            o
            for o in pool
            if o is not r
            and is_horizontal(o)
            and 0 <= o.bbox[1] - r.bbox[3] + 2 <= max_gap_factor * r.size
            and x_overlap(r.bbox, o.bbox) > 0.3 * min(r.bbox[2] - r.bbox[0], o.bbox[2] - o.bbox[0])
        ]
        return min(cands, key=lambda o: o.bbox[1]) if cands else None

    def _below_label(self, r: TextRun, pool: list[TextRun], max_gap_factor=2.5) -> TextRun | None:
        """Nearest run below r within the same title-block cell: label sits above its value, the value
        may be a larger font and shifted right rather than x-aligned (unlike `_below`'s row-continuation use)."""
        width = max(r.bbox[2] - r.bbox[0], 40)
        cands = [
            o
            for o in pool
            if o is not r
            and is_horizontal(o)
            and 0 <= o.bbox[1] - r.bbox[3] + 2 <= max_gap_factor * r.size
            and r.bbox[0] - 10 <= o.bbox[0] < r.bbox[0] + 4 * width
        ]
        return min(cands, key=lambda o: o.bbox[1]) if cands else None

    def _circle_containing(self, r: TextRun, min_d=10, max_d=60):
        cx, cy = r.center
        best = None
        for c in self.s.circles:
            if not (min_d <= c.diameter <= max_d):
                continue
            x0, y0, x1, y1 = c.bbox
            if x0 - 2 <= cx <= x1 + 2 and y0 - 2 <= cy <= y1 + 2:
                if best is None or c.diameter < best.diameter:
                    best = c
        return best
