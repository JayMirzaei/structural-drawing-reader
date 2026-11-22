"""The per-sheet parser: all rule groups combined, run in a fixed order."""

from __future__ import annotations

from drawing_reader.parse.sheet.dimensions import DimensionsMixin
from drawing_reader.parse.sheet.members import MembersMixin
from drawing_reader.parse.sheet.notes import NotesMixin
from drawing_reader.parse.sheet.revisions import RevisionsMixin
from drawing_reader.parse.sheet.symbols import SymbolsMixin
from drawing_reader.parse.sheet.titleblock import TitleBlockMixin
from drawing_reader.schema import Fact, SheetMeta


class SheetParser(TitleBlockMixin, RevisionsMixin, NotesMixin, MembersMixin, SymbolsMixin, DimensionsMixin):
    """Parses one sheet into facts.

    The order in `run` matters: each rule marks the text runs it consumed (`self.used`), so earlier,
    more specific rules (revision rows, member labels, weld sizes) keep later, more general ones (notes,
    dimensions, leftover text) from claiming the same text."""

    def run(self, common_large_texts: set[str]) -> tuple[SheetMeta, list[Fact]]:
        self.parse_revision_header_table()
        self.parse_titleblock(common_large_texts)
        self.parse_sheet_scale()
        self.parse_location()
        if not any(f.kind == "revision" for f in self.facts):
            self.parse_revision_table_banded()  # only when neither earlier reader found anything
        if not any(f.kind == "revision" for f in self.facts):
            # header wording that varies (REV NO., REVISION, NO.) and a header at the table's foot
            self.parse_revision_header_table(variants=True)
        if not any(f.kind == "revision" for f in self.facts):
            # dotted revision codes (0.A.0) lead a row of description and date, header or not
            self.parse_revision_rows_by_code()
        self.parse_labels()
        self.parse_grids_callouts_elevations()
        self.merge_view_number_markers()
        self.parse_welds()
        self.parse_load_table()
        self.parse_notes()
        self.parse_dimensions()
        self.parse_remaining_text()
        self.assign_views()
        self.assign_scale_consensus()
        for f in self.facts:
            f.sheet = self.meta.number
            f.id = f.id.replace("@", self.meta.number, 1)
            f.links = [link.replace("@", self.meta.number, 1) for link in f.links]
        return self.meta, self.facts
