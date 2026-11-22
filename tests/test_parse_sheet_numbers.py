"""Sheet and document numbers: labelled fields, boxed numbers, long document numbers, numbers
split over two runs, and the title-block texts that are never a number. Every input is invented."""

from __future__ import annotations

import pytest

from drawing_reader.parse.scale import RE_SCALE_LABELLED
from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.parse.sheet_numbers import (
    RE_SHEET_NO,
    document_number_text,
    fuzzy_number_label,
    is_page_count,
    join_split_numbers,
)
from drawing_reader.parse.titleblock_fields import plausible_project_no
from support import make_run, make_sheet


def run(text, x0, y0, x1, y1, size, **kw):
    """A text run with an explicit box (x0, y0, x1, y1)."""
    return make_run(text, x0, y0, size, x1=x1, y1=y1, **kw)


def read_titleblock(runs, width=1224, height=792):
    """Parse only the title block of a hand-built sheet."""
    parser = SheetParser(make_sheet(runs, width=width, height=height))
    parser.parse_titleblock(set())
    return parser


def boxed_block(scale="AS NOTED", x=980, y=646):
    """A title block with a big number in a box, the "SH.NO. n OF m" caption under it, field rows,
    then company / town / title lines and a plot stamp at the foot."""
    rows = [
        ("S6", x + 150, y, x + 178, y + 23, 22.0),
        ("SH.NO.", x + 128, y + 28, x + 154, y + 37, 9.0),
        ("OF8", x + 156, y + 36, x + 181, y + 46, 10.0),
        ("DRAWN BY", x, y + 10, x + 36, y + 21, 10.0),
        ("KT/MB", x + 43, y + 10, x + 70, y + 21, 10.0),
        ("DATE", x, y + 24, x + 20, y + 33, 9.0),
        ("MARCH 2031", x + 42, y + 24, x + 88, y + 34, 10.0),
        ("SCALE", x, y + 36, x + 23, y + 47, 11.0),
        (scale, x + 43, y + 36, x + 89, y + 47, 10.0),
        ("LARKSPURFABRICATION", x + 1, y + 49, x + 124, y + 60, 12.0),
        ("HARLOWCREEK,MANITOBA", x + 2, y + 81, x + 134, y + 91, 12.0),
        ("SECTIONS", x + 1, y + 101, x + 60, y + 114, 12.0),
        ("03/14/2031 2:41:07 PM", x + 2, y + 116, x + 72, y + 126, 10.0),
    ]
    return [run(*row) for row in rows]


# --- the number beside or under its label ---------------------------------------------------------


def test_a_labelled_number_may_have_a_leading_zero():
    """Under "DRAWING NO.:" a value is the number even when it breaks the usual shape ("S0403": the
    sheet-number pattern allows three digits at most)."""
    runs = [
        run("DRAWING NO.:", 880, 704, 940, 714, 9.5),
        run("S0403", 885, 718, 970, 754, 36.0),
        run("AS NOTED", 590, 744, 670, 756, 12.0),
    ]
    assert not RE_SHEET_NO.match("S0403")
    assert read_titleblock(runs).meta.number == "S0403"


def test_a_labelled_number_that_lost_its_leading_part_is_kept_as_read():
    """A document number whose prefix was cut off still stands under its label; a later pass
    completes it from the other sheets."""
    runs = [run("DRAWING NO", 880, 704, 940, 714, 9.5), run("-31-STL-PR3-0020-006", 885, 718, 1080, 740, 21.9)]
    assert read_titleblock(runs).meta.number == "-31-STL-PR3-0020-006"


def test_a_misspelt_number_label_still_marks_the_number():
    """A scan's "DRAWIMG NO." is still the number label, so the value under it is the number."""
    runs = [run("DRAWIMG NO.", 880, 704, 940, 714, 9.5), run("C004", 885, 718, 970, 744, 24.0)]
    assert read_titleblock(runs).meta.number == "C004"


def test_only_a_long_misspelling_counts_as_a_number_label():
    """A label within a letter or two of "DRAWINGNO" matches; a lone "SHEET" or "NO" never does."""
    assert fuzzy_number_label("DRAWIMGNO") is not None and fuzzy_number_label("DRAVNGNO") is not None
    assert fuzzy_number_label("SHEET") is None and fuzzy_number_label("NO") is None


def test_the_number_comes_from_the_drawing_number_field_not_the_paper_size():
    """ "A1" beside "SHEET SIZE" looks like a sheet number; the value of "DRAWING #" is the number,
    and a consultant's own number quoted in one run with its label is not."""
    runs = [
        run("SHEET SIZE", 690, 704, 750, 712, 6),
        run("A1", 770, 704, 782, 712, 6),
        run("DRAWING #", 690, 744, 740, 752, 6),
        run("LKF-S00-40312", 750, 744, 830, 754, 8),
        run("CONSULTANT DRAWING #: S210", 690, 764, 830, 772, 6),
    ]
    assert read_titleblock(runs, width=900, height=800).meta.number == "LKF-S00-40312"


def test_a_boxed_number_over_its_caption_wins_over_the_page_count_beside_it():
    """The big number in the box is the sheet number, not the "OF8" of "n OF m" under it; the scale
    word beside its label is read with its misread letter repaired."""
    parser = read_titleblock(boxed_block(scale="AS INDlCATED"))
    assert parser.meta.number == "S6"
    assert parser.meta.scale == "AS INDICATED"


# --- long document numbers ------------------------------------------------------------------------


def test_a_long_document_number_beats_a_short_mark_in_the_title_block():
    """On an industrial sheet the segmented document number is the sheet's number, not a short mark
    that happens to look like "S1"."""
    runs = [run("TR2", 690, 704, 720, 716, 10.0), run("HC2-31-STL-07-0044-003", 790, 724, 930, 738, 12.4)]
    assert read_titleblock(runs).meta.number == "HC2-31-STL-07-0044-003"


def test_a_sheet_style_number_set_larger_than_the_document_number_stays():
    """A building-style number in large lettering is the sheet number even with a document number
    printed small beside it."""
    runs = [run("S-201", 690, 704, 750, 730, 24.0), run("HC2-31-STL-07-0044-003", 790, 724, 930, 738, 8.0)]
    assert read_titleblock(runs).meta.number == "S-201"


def test_a_document_number_cut_after_its_prefix_without_the_dash_is_joined():
    """A scan reads "HC2" and "31-STL-..." as two runs and loses the dash between them: together
    they are the number."""
    runs = [
        run("DRAWING NO.", 2001, 1643, 2058, 1656, 13.0),
        run("HC2", 2008, 1654, 2044, 1675, 18.0),
        run("31-STL-PR3-0020-011", 2058, 1654, 2310, 1675, 22.0),
    ]
    assert read_titleblock(runs, width=2592, height=1728).meta.number == "HC2-31-STL-PR3-0020-011"


def test_a_lone_dash_between_two_runs_of_one_row_joins_them_into_one_number():
    """ "K-B204-3310" "-" "105" read as three runs is one document number spanning all three."""
    runs = [
        run("K-B204-3310", 2630, 1904, 2725, 1927, 19.9),
        run("-", 2727, 1906, 2733, 1926, 17.9),
        run("105", 2735, 1904, 2762, 1927, 19.9),
    ]
    joined = join_split_numbers(runs)
    assert [r.text for r in joined] == ["K-B204-3310-105"]
    assert joined[0].bbox == (2630, 1904, 2762, 1927)


# --- shapes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("number", ["S-3-21", "S-5-7", "S-8-12", "S-2-2", "S-2310-04"])
def test_dashed_area_and_series_numbers_match_the_sheet_number_shape(number):
    """Discipline-area-sheet ("S-3-21") and series-drawing-sheet ("S-2310-04") numbers are sheet
    numbers."""
    assert RE_SHEET_NO.match(number)


def test_a_bare_drawing_series_is_not_a_sheet_number():
    assert not RE_SHEET_NO.match("2310")


@pytest.mark.parametrize("text", ["OF8", "2 OF 8", "SHT.2OF5", "3OF8"])
def test_a_page_count_is_not_a_sheet_number(text):
    """ "n OF m" beside a sheet-number label, in whatever pieces a scan read it."""
    assert is_page_count(text)


@pytest.mark.parametrize("text", ["S2", "OF-200", "A201", "S-3.2"])
def test_a_sheet_number_is_not_a_page_count(text):
    assert not is_page_count(text)


# --- candidate clean-up: what a run offers as a document number -------------------------------------


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("RE.FDWG.NO.407315", "407315"),  # a label glued in front, with part of the next cell
        ("DWG.NO.S-201", "S-201"),
        ("4410-P007", "4410-P007"),
    ],
)
def test_a_glued_number_label_is_dropped_from_the_number(text, number):
    assert document_number_text(make_run(text, 0, 0)) == number


@pytest.mark.parametrize(
    "text",
    [
        "MAR-17-2021",  # a plot date
        "07-Mar-2021",
        "19-SEP-22",
        "03-FEB-2020",
        "FAX:5550100",  # a fax line
        "KT2.APPROVED",  # an approval stamp glued to initials
        "08-41-17-3-W5M",  # a land location
    ],
)
def test_dates_stamps_and_contact_lines_are_not_document_numbers(text):
    """Segmented like a document number, but a date, a fax line, a stamp or a land location."""
    assert document_number_text(make_run(text, 0, 0)) == ""


def test_a_tilde_read_for_a_dash_is_mended_on_a_scan_only():
    """A scan reads a dash as "~"; in vector text the character is left as drawn."""
    assert document_number_text(make_run("1100SFRM~002304", 0, 0, conf=0.9)) == "1100SFRM-002304"
    assert document_number_text(make_run("1100SFRM~002304", 0, 0)) == "1100SFRM~002304"


# --- project numbers and member marks ---------------------------------------------------------------


@pytest.mark.parametrize("text", ["3107-014", "P41207", "31-006", "300.1200.000.041.007", "40713-0005"])
def test_a_project_number_is_mostly_digits_and_separators(text):
    assert plausible_project_no(text)


@pytest.mark.parametrize("text", ["NTS", "EAST RACK (BAY 3)", "CHECKD BY:", "PHASE 2 LOCATION KEY PLAN"])
def test_words_beside_a_project_number_label_are_not_the_number(text):
    """A value needs digits: a neighbouring label or a title is not a project number."""
    assert not plausible_project_no(text)


def test_two_letter_member_prefixes_are_member_labels():
    """ "PL9.5" and "WT155X26" start with two letters like a sheet number ("SK12"), but are a plate and
    a tee."""
    parser = SheetParser(
        make_sheet([make_run("PL9.5", 100, 100, 9), make_run("WT155X26", 100, 130, 9)], width=792, height=612)
    )
    parser.parse_labels()
    assert {f.attrs["section"] for f in parser.facts if f.kind == "label"} == {"PL9.5", "WT155X26"}


# --- the scale field of the same block --------------------------------------------------------------


def test_scale_is_read_under_its_label_when_the_run_beside_it_is_another_label():
    """ "SCALE" with "DRAWING NO" on its right and the value below: the value below is the scale."""
    runs = [
        run("SCALE", 875, 704, 909, 718, 14.1),
        run("DRAWING NO", 940, 704, 1000, 714, 9.9),
        run("1:50", 880, 720, 924, 744, 23.1),
    ]
    parser = SheetParser(make_sheet(runs))
    parser.parse_sheet_scale()
    assert parser.meta.scale == "1:50"


def test_a_word_scale_in_the_block_wins_over_numeric_view_scales_beside_it():
    """A sheet whose block says "AS SHOWN" carries several view scales: the block's word is the
    sheet scale, not the commonest view scale."""
    runs = boxed_block(scale="AS SHOWN") + [run("1:25", 100, 704, 120, 714, 8.0), run("1:50", 200, 704, 220, 714, 8.0)]
    parser = SheetParser(make_sheet(runs))
    parser.tb, parser.body = runs, []
    parser.parse_sheet_scale()
    assert parser.meta.scale == "AS SHOWN"


@pytest.mark.parametrize("text", ["Scdle:AS SHOWN", "Soale: 1:25"])
def test_a_scan_misreading_the_word_scale_still_gives_a_labelled_scale(text):
    """ "Scale" read as "Scdle" or "Soale" is still the scale label."""
    assert RE_SCALE_LABELLED.match(text)
