"""Revision tables that do not follow the common layout: other header wording, the header at the
foot of the table, rows led by a dotted code, and a numbered note under the table. Every input is
invented."""

from __future__ import annotations

from drawing_reader.parse.sheet.parser import SheetParser
from support import make_run, make_sheet


def row(y, height, size, *cells):
    """One printed row: cells are (text, x0, x1), all on the baseline at `y`."""
    return [make_run(text, x0, y, size, x1=x1, y1=y + height) for text, x0, x1 in cells]


def revisions(parser):
    return [(f.attrs["number"], f.attrs["date"], f.attrs["description"]) for f in parser.facts if f.kind == "revision"]


def test_a_header_at_the_foot_of_the_table_with_a_date_format_for_a_heading():
    """Header "No. | YYYY-MM-DD | DESCRIPTION" is the bottom row; the revision sits above it."""
    runs = row(506, 10, 10.0, ("No.", 390, 410), ("YYYY-MM-DD", 430, 490), ("DESCRIPTION", 510, 590))
    runs += row(490, 10, 10.0, ("1", 395, 402), ("2031-03-18", 430, 485), ("ISSUED FOR TENDER", 510, 600))
    parser = SheetParser(make_sheet(runs))
    parser.parse_revision_header_table(variants=True)
    assert revisions(parser) == [("1", "2031-03-18", "ISSUED FOR TENDER")]


def test_a_bare_number_header_without_a_date_column_is_not_a_revision_table():
    """ "No." and "DESCRIPTION" alone head many tables (a legend, a bill of material)."""
    runs = row(506, 10, 10.0, ("No.", 390, 410), ("DESCRIPTION", 510, 590))
    runs += row(490, 10, 10.0, ("1", 395, 402), ("ISSUED FOR TENDER", 510, 600))
    parser = SheetParser(make_sheet(runs))
    parser.parse_revision_header_table(variants=True)
    assert revisions(parser) == []


def test_a_header_reading_rev_hash_and_date_colon_is_a_revision_header():
    """ "REV#", "DATE:", "DESCRIPTION" at the foot, newest revision next to the header."""
    runs = row(1215, 8, 7.6, ("REV#", 2295, 2312), ("DATE:", 2323, 2342), ("DESCRIPTION", 2360, 2403))
    runs += row(1201, 8, 7.6, ("1", 2298, 2304), ("08/23/31", 2323, 2352), ("ISSUED FOR PERMIT", 2360, 2423))
    runs += row(1188, 8, 7.6, ("2", 2298, 2304), ("02/07/32", 2323, 2352), ("ISSUED FOR TENDER", 2360, 2423))
    parser = SheetParser(make_sheet(runs, width=2592, height=1728))
    parser.parse_revision_header_table(variants=True)
    assert revisions(parser) == [("2", "02/07/32", "ISSUED FOR TENDER"), ("1", "08/23/31", "ISSUED FOR PERMIT")]


def test_initials_in_a_neighbouring_column_do_not_spoil_a_row():
    """A "by" column without a heading sits between description and date; the row still reads, with a
    date-format heading a scan misspelt."""
    runs = row(553, 7.2, 7.2, ("ISSUE", 434, 446), ("DESCRIPTION", 475, 497), ("YY-MM-DO", 544, 565))
    runs += row(
        542, 7.2, 7.2, ("B", 438, 441), ("FOR COORDINATION", 452, 484), ("MB", 529, 536), ("31/05/14", 546, 565)
    )
    parser = SheetParser(make_sheet(runs, width=792, height=612))
    parser.parse_revision_header_table(variants=True)
    assert [(number, date) for number, date, _ in revisions(parser)] == [("B", "31/05/14")]


def test_rows_led_by_a_dotted_revision_code_are_read_without_a_header():
    """Some owners number revisions "0.B.0", "0.B.1": a row of code, description and date is a
    revision whether or not a header was found."""
    runs = row(672, 10, 10.0, ("0.B.0", 550, 570), ("ISSUED FOR REVIEW", 578, 640), ("2030/04/09", 709, 741))
    runs += row(684, 10, 10.0, ("0.B.1", 550, 570), ("ISSUED FOR CONSTRUCTION", 578, 653), ("2031/11/02", 709, 741))
    parser = SheetParser(make_sheet(runs))
    parser.parse_revision_rows_by_code()
    assert revisions(parser) == [
        ("0.B.0", "2030/04/09", "ISSUED FOR REVIEW"),
        ("0.B.1", "2031/11/02", "ISSUED FOR CONSTRUCTION"),
    ]


def test_a_numbered_note_under_the_revision_table_is_not_a_revision_row():
    """A general note printed under the table has a number and may carry a date beside it; a row
    whose description reads like a sentence of a note is left out."""
    runs = row(704, 8, 8.0, ("NO.", 590, 610), ("REVISION", 630, 690), ("DATE", 890, 920), ("BY", 990, 1005))
    runs += row(689, 8, 8.0, ("1", 593, 600), ("ISSUED FOR TENDER", 630, 740), ("2031.06.14", 890, 940))
    note = "ALL ELEVATIONS SHALL BE CONFIRMED ON SITE BEFORE FABRICATION."
    runs += row(674, 8, 8.0, ("3", 593, 600), (note, 630, 870), ("2031.02.01", 890, 940))
    parser = SheetParser(make_sheet(runs))
    parser.parse_titleblock(set())
    parser.parse_revision_table_banded()
    descriptions = [description for _, _, description in revisions(parser)]
    assert any("ISSUED FOR TENDER" in d for d in descriptions)
    assert not any("SHALL" in d for d in descriptions)
