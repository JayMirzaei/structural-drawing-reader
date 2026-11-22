"""Fillet-weld symbols: reading the triangle glyph and its size from line geometry, and answering
weld questions from the symbols found."""

from __future__ import annotations

from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.qa import answer, tokens
from drawing_reader.qa.rules.members import rule_weld
from support import make_fact, make_index, make_run, make_sheet, segment

LEG = 16.0  # leg length of the hand-built triangle glyphs, in points


def weld_glyph(x: float, y: float, below: bool = True, above: bool = False) -> list:
    """A reference line from (x, y) one leg long, with a right-triangle glyph below and/or above it."""
    segments = [segment(x, y, x + LEG, y)]
    for wanted, sign in ((below, 1), (above, -1)):
        if wanted:
            segments.append(segment(x, y, x, y + sign * LEG))
            segments.append(segment(x, y + sign * LEG, x + LEG, y))
    return segments


def parse_welds(runs, segments):
    parser = SheetParser(make_sheet(runs, segments))
    parser.parse_welds()
    return parser, [f for f in parser.facts if f.kind == "weld"]


def test_every_weld_symbol_on_the_detail_sheet_is_read(platform):
    """Each detail carries one fillet-weld symbol; every one is read with its size, and none is
    invented on the sheets that draw no symbol."""
    welds = platform.by_kind("weld")
    assert len(welds) == 3
    assert {w.sheet for w in welds} == {"S-301"}
    assert all(w.value == "6" and w.unit == "mm" for w in welds)
    assert {w.view for w in welds} == {"COLUMN BASE PLATE", "BEAM TO COLUMN SHEAR TAB", "BRACE GUSSET AT COLUMN BASE"}


def test_weld_size_and_typ_tag_are_not_read_again_as_dimension_or_note(platform):
    """A weld size sits on a thin line just like a dimension string, and its 'TYP.' tag looks like a
    short note. The weld reader runs first and claims both, so neither shows up as another fact."""
    on_details = [f for f in platform.facts if f.sheet == "S-301"]
    assert [f for f in on_details if f.kind == "dimension" and f.source_text.strip() == "6"] == []
    assert [f for f in on_details if f.kind in ("note", "text") and f.source_text.strip() == "TYP."] == []
    assert sum(1 for f in on_details if f.kind == "weld" and f.attrs["typical"]) == 2


def test_weld_question_is_scoped_to_the_detail_it_names(platform):
    """A question naming a detail gets that detail's symbol, with the detail cited as evidence."""
    a = answer("What is the weld size at the brace gusset?", platform, llm=None)
    assert a.method == "rule:weld"
    assert "6 mm fillet, both sides (typ.)" in a.text
    cited = [platform.get(fid) for fid in a.fact_ids]
    assert [(f.sheet, f.view) for f in cited] == [("S-301", "BRACE GUSSET AT COLUMN BASE")]


def test_weld_rule_yields_when_no_symbol_was_read():
    """A set that states its welds only in prose has no weld facts: the rule must step aside for the
    keyword search instead of answering confidently about nothing."""
    prose = make_fact("S-101.note.001", "note", "ALL WELDS SHALL BE CONTINUOUS FILLET WELDS", "S-101", number="1")
    q = "what welds are shown?"
    assert rule_weld(q, tokens(q), make_index(prose)) is None


def test_symbol_on_both_sides_with_typical_tag():
    """Triangles above and below one reference line are a weld on both sides: one fact, with the two
    size numbers and the 'TYP.' tag to the right of the line all consumed."""
    size_below = make_run("10", 286, 414, 8, x1=296, y1=425, run_id="p1.below")
    size_above = make_run("10", 286, 396, 8, x1=296, y1=407, run_id="p1.above")
    typ = make_run("TYP.", 330, 405, 8, x1=350, y1=416, run_id="p1.typ")
    parser, welds = parse_welds([size_below, size_above, typ], weld_glyph(300, 410, below=True, above=True))
    assert len(welds) == 1
    assert welds[0].value == "10"
    assert welds[0].attrs["sides"] == "both"
    assert welds[0].attrs["typical"] is True
    assert {size_below.id, size_above.id, typ.id} <= parser.used


def test_symbol_below_the_line_only_is_the_arrow_side():
    """A triangle drawn only below the reference line is the arrow side; with no 'TYP.' tag nearby
    the weld is not marked typical."""
    size = make_run("5", 288, 414, 8, x1=296, y1=425)
    _, welds = parse_welds([size], weld_glyph(300, 410))
    assert len(welds) == 1
    assert welds[0].value == "5"
    assert welds[0].attrs["sides"] == "arrow"
    assert welds[0].attrs["typical"] is False


def test_symbol_without_a_size_gives_no_fact():
    """A triangle glyph with no number beside it is geometry only: no weld fact with an empty or
    guessed size."""
    _, welds = parse_welds([], weld_glyph(300, 410))
    assert welds == []
