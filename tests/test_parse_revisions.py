"""Revision tables in layouts other than the plain "REV | DATE | DESCRIPTION" header over its
rows: other header words, a header at the foot of the table, cells that wrap, an initials column."""

from __future__ import annotations

from drawing_reader.parse import SheetParser
from support import make_run, make_sheet


def _cell(text, x0, y0, x1, size=10.0):
    return make_run(text, x0, y0, size, x1=x1, y1=y0 + 10)


def _revisions(runs, width=2448, height=1584):
    """(number, date, description) of every revision row, read by the two table readers in turn."""
    parser = SheetParser(make_sheet(runs, width=width, height=height))
    parser.parse_revision_header_table()
    parser.parse_revision_table_banded()
    return sorted(
        (f.attrs["number"], f.attrs["date"], f.attrs["description"]) for f in parser.facts if f.kind == "revision"
    )


def test_rows_under_a_no_header_with_dates_wrapped_over_two_lines():
    """Header "No. | Date | Description" with the rows below; a date ("MAR 14" over "2031") and a
    description may each wrap onto a second line of the same row."""
    runs = [
        _cell("No.", 2176, 74, 2191),
        _cell("Date", 2209, 74, 2230),
        _cell("Description", 2249, 74, 2300),
        _cell("1", 2181, 90, 2186),
        _cell("MAR 14", 2204, 90, 2230),
        _cell("PRELIMINARY LAYOUT", 2248, 90, 2340),
        _cell("2031", 2210, 100, 2230),
        _cell("2", 2181, 114, 2186),
        _cell("OCT 08", 2204, 114, 2230),
        _cell("ISSUED FOR CLIENT", 2248, 114, 2345),
        _cell("2031", 2210, 125, 2230),
        _cell("REVIEW-DRAFT", 2248, 125, 2320),
    ]
    assert _revisions(runs) == [
        ("1", "MAR 14 2031", "PRELIMINARY LAYOUT"),
        ("2", "OCT 08 2031", "ISSUED FOR CLIENT REVIEW-DRAFT"),
    ]


def test_header_at_the_foot_of_the_table_with_rows_listed_upward():
    """Header "I/R | DATE | DESCRIPTION" is the last row and revisions stack upward, newest on top;
    a run holding the date and the description together is split."""
    runs = [
        _cell("I/R", 1913, 1224, 1926),
        _cell("DATE", 1950, 1224, 1972),
        _cell("DESCRIPTION", 2039, 1224, 2100),
        _cell("3", 1916, 1145, 1921),
        _cell("FEB", 1930, 1145, 1948),
        _cell("RE-ISSUED FOR", 2001, 1145, 2070),
        _cell("17/2032", 1930, 1156, 1960),
        _cell("FABRICATION", 2001, 1156, 2065),
        _cell("1", 1916, 1196, 1921),
        _cell("NOV. 05/2031 ISSUED FOR REVIEW", 1930, 1196, 2080),
        _cell("0", 1916, 1210, 1921),
        _cell("JUL 22/2031", 1930, 1210, 1980),
        _cell("ISSUED FOR QUOTATION", 2001, 1210, 2095),
    ]
    assert _revisions(runs, width=2200, height=1700) == [
        ("0", "JUL 22/2031", "ISSUED FOR QUOTATION"),
        ("1", "NOV. 05/2031", "ISSUED FOR REVIEW"),
        ("3", "FEB 17/2032", "RE-ISSUED FOR FABRICATION"),
    ]


def test_a_no_and_description_table_without_a_date_column_is_not_a_revision_table():
    """A bare "No." header beside "Description" heads many kinds of table; with no date column and
    no numbered row it is not read as revisions."""
    runs = [_cell("No.", 300, 80, 320), _cell("Description", 340, 80, 400), _cell("PLATFORM", 340, 96, 400)]
    assert _revisions(runs) == []


def test_numbered_notes_under_a_no_and_description_header_are_not_revisions():
    """A numbered list whose second column is prose, with no date anywhere, is a notes table."""
    runs = [
        _cell("NO.", 300, 80, 320),
        _cell("DESCRIPTION", 340, 80, 405),
        _cell("4", 302, 96, 308),
        _cell("ANCHOR RODS TO BE HOT DIP GALVANIZED", 340, 96, 560),
    ]
    assert _revisions(runs) == []


def test_initials_in_a_by_column_are_not_part_of_the_description():
    """A "BY" column right of the description holds the drafter's initials: kept apart as `by`."""
    runs = [
        _cell("REV", 200, 500, 220),
        _cell("DATE", 240, 500, 270),
        _cell("DESCRIPTION", 300, 500, 380),
        _cell("BY", 520, 500, 532),
        _cell("2", 204, 480, 210),
        _cell("14.03.31", 240, 480, 275),
        _cell("ISSUED FOR ANCHOR RODS", 300, 480, 435),
        _cell("KV", 521, 480, 532),
    ]
    parser = SheetParser(make_sheet(runs, width=900, height=700))
    parser.parse_revision_table_banded()
    row = next(f for f in parser.facts if f.kind == "revision")
    assert (row.attrs["number"], row.attrs["date"], row.attrs["description"], row.attrs["by"]) == (
        "2",
        "14.03.31",
        "ISSUED FOR ANCHOR RODS",
        "KV",
    )
