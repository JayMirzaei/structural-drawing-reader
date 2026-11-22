"""Notes: notes written in the title-block strip, bullets and numbers glued to their text, lettered
items, field labels that are not headings, and a number that opens a line of words. Every input is
invented."""

from __future__ import annotations

from drawing_reader.parse.note_text import split_numbered_items
from drawing_reader.parse.sheet.parser import SheetParser
from support import make_run, make_sheet, segment


def run(text, x0, y0, x1, y1, size, **kw):
    """A text run with an explicit box (x0, y0, x1, y1)."""
    return make_run(text, x0, y0, size, x1=x1, y1=y1, **kw)


def read_notes(runs):
    """Parse only the notes of a hand-built letter-size sheet; returns the note facts."""
    parser = SheetParser(make_sheet(runs, width=792, height=612))
    parser.parse_notes()
    return [f for f in parser.facts if f.kind == "note"]


def dimensions_of(runs, segments):
    parser = SheetParser(make_sheet(runs, segments, width=842, height=595))
    parser.parse_dimensions()
    return [f.value for f in parser.facts if f.kind == "dimension"]


def test_a_note_in_the_title_block_strip_is_read_but_title_lines_and_paths_are_not():
    """A note written in the bottom band is a note (marked as found in the title block); the sheet's
    title line, a plot-file path and the copyright line beside it are not."""
    texts = [
        "ALL ANCHOR RODS TO BE SET BY TEMPLATE U.N.O.",
        "ROOF FRAMING PLAN AND DETAILS FOR BAY 2",
        "P:\\\\JOBS\\\\STL\\\\CAD\\\\ROOF FRAMING PLAN SHEET NOTE ONLY",
        "COPYRIGHT RESERVED THIS DRAWING IS THE PROPERTY OF THE DESIGNER",
    ]
    ys = (522, 546, 570, 590)
    runs = [run(text, 64, y, 334, y + 12, 8, block=i) for i, (text, y) in enumerate(zip(texts, ys, strict=True))]
    notes = read_notes(runs)
    assert [f.value for f in notes] == ["ALL ANCHOR RODS TO BE SET BY TEMPLATE U.N.O."]
    assert notes[0].attrs["in_titleblock"] is True


def test_bullets_and_item_numbers_glued_to_their_text_start_items():
    """A CAD export prints a list as one block with "-TEXT" and "14.TEXT": each is its own item, with
    the dash read as a bullet and the number kept."""
    runs = [
        run("GENERAL NOTES:", 54, 72, 204, 82, 9),
        run("-THE FABRICATOR SHALL SUBMIT SHOP DRAWINGS FOR REVIEW", 54, 92, 404, 102, 8),
        run("-ALL BOLTS SHALL CONFORM TO ASTM A325M UNLESS NOTED", 54, 106, 404, 116, 8),
        run("14.PROVIDE STIFFENERS AT ALL BEARING POINTS", 54, 132, 404, 142, 8),
    ]
    items = [(f.attrs["number"], f.value) for f in read_notes(runs) if f.attrs.get("role") != "heading"]
    assert items == [
        ("•", "THE FABRICATOR SHALL SUBMIT SHOP DRAWINGS FOR REVIEW"),
        ("•", "ALL BOLTS SHALL CONFORM TO ASTM A325M UNLESS NOTED"),
        ("14", "PROVIDE STIFFENERS AT ALL BEARING POINTS"),
    ]


def test_a_lettered_item_keeps_its_letter():
    """ "A." in its own run, then the text: the item is note A under the heading above it."""
    runs = [
        run("WELDING:", 54, 72, 120, 82, 9),
        run("A.", 54, 92, 62, 102, 8),
        run("ALL WELDS TO BE CONTINUOUS FILLET WELDS", 70, 92, 330, 102, 8),
    ]
    items = [f for f in read_notes(runs) if f.attrs.get("role") != "heading"]
    assert [(f.attrs["number"], f.value, f.attrs["heading"]) for f in items] == [
        ("A", "ALL WELDS TO BE CONTINUOUS FILLET WELDS", "Welding")
    ]


def test_a_title_block_field_label_is_not_a_note_heading():
    """ "CLIENT:" is capitals ending in a colon like a heading, but it is a field label."""
    runs = [
        run("CLIENT:", 54, 42, 124, 52, 8),
        run("GENERAL NOTES:", 54, 72, 204, 82, 9),
        run("1.", 54, 92, 62, 102, 8),
        run("ALL STEEL TO BE SHOP PRIMED", 70, 92, 300, 102, 8),
    ]
    headings = [f.value for f in read_notes(runs) if f.attrs.get("role") == "heading"]
    assert headings == ["GENERAL NOTES:"]


def test_two_items_merged_into_one_line_are_split_at_the_next_number():
    """ "... 4.8 kPa. 4. SEE PLAN" under item 3 is items 3 and 4; a number that is not the next
    item ("USE 4. MM SHIMS") does not split the note."""
    assert split_numbered_items("3", "LIVE LOAD 4.8 kPa. 4. SEE PLAN") == [
        ("3", "LIVE LOAD 4.8 kPa."),
        ("4", "SEE PLAN"),
    ]
    assert split_numbered_items("3", "USE 4. MM SHIMS") == [("3", "USE 4. MM SHIMS")]


def test_a_number_opening_a_line_of_words_is_a_note_not_a_dimension():
    """A number over a line is a dimension when alone or followed by its own qualifier ("TYP",
    "VARIES"); followed by other words ("45 TIES AT EACH END") it opens a note."""
    line = [segment(64, 98, 344, 98, 0.7)]
    number = run("45", 104, 88, 116, 96, 7.9)

    def words(text):
        return run(text, 119, 88, 119 + 6 * len(text), 96, 7.9)

    assert dimensions_of([number], line) == ["45"]
    assert dimensions_of([number, words("TIES AT EACH END")], line) == []
    assert dimensions_of([number, words("TYP")], line) == ["45"]
    assert dimensions_of([number, words("VARIES")], line) == ["45"]
