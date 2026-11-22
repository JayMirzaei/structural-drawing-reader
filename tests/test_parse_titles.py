"""Sheet titles: where a title is found in a title block, how a scanned title is repaired, and
which lines of a title block are never a title. Every input is invented."""

from __future__ import annotations

import pytest

from drawing_reader.parse.revision_text import RE_REV_CODE
from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.parse.titleblock_fields import fuzzy_label_line
from drawing_reader.parse.titles import (
    RE_SHEET_OF,
    RE_TITLE_WORD,
    fix_title_digits,
    plausible_title,
    split_glued_title,
    trim_stray_labels,
)
from support import make_run, make_sheet


def run(text, x0, y0, x1, y1, size, **kw):
    """A text run with an explicit box (x0, y0, x1, y1)."""
    return make_run(text, x0, y0, size, x1=x1, y1=y1, **kw)


def read_titleblock(runs, width=1224, height=792, repeated=()):
    """Parse only the title block of a hand-built sheet; `repeated` are texts found on most sheets."""
    parser = SheetParser(make_sheet(runs, width=width, height=height))
    parser.repeated = set(repeated)
    parser.parse_titleblock(set())
    return parser


def scanned_block(title, x=980, y=646):
    """A scanned title block as OCR gives it: a boxed number over its "n of m" caption, field rows,
    then an unlabelled stack of company / town / title lines and a plot stamp at the foot."""
    rows = [
        ("S6", x + 150, y, x + 178, y + 23, 22.0),
        ("SH.NO.", x + 128, y + 28, x + 154, y + 37, 9.0),
        ("OF8", x + 156, y + 36, x + 181, y + 46, 10.0),
        ("DRAWN BY", x, y + 10, x + 36, y + 21, 10.0),
        ("KT/MB", x + 43, y + 10, x + 70, y + 21, 10.0),
        ("DATE", x, y + 24, x + 20, y + 33, 9.0),
        ("MARCH 2031", x + 42, y + 24, x + 88, y + 34, 10.0),
        ("SCALE", x, y + 36, x + 23, y + 47, 11.0),
        ("AS NOTED", x + 43, y + 36, x + 85, y + 47, 10.0),
        ("LARKSPURFABRICATION", x + 1, y + 49, x + 124, y + 60, 12.0),
        ("HARLOWCREEK,MANITOBA", x + 2, y + 81, x + 134, y + 91, 12.0),
        (title, x + 1, y + 101, x + 1 + 5.5 * len(title), y + 114, 12.0),
        ("03/14/2031 2:41:07 PM", x + 2, y + 116, x + 72, y + 126, 10.0),
    ]
    return [run(*row, conf=0.95) for row in rows]


# --- where the title is --------------------------------------------------------------------------


def test_title_is_the_block_of_lines_under_a_title_label():
    """Under a "TITLE" label the title is the stack of lines; a line repeated on every sheet (the
    project name) is dropped from its head, and the document number below is not part of it."""
    runs = [
        run("TITLE", 906, 694, 918, 702, 8.0),
        run("HARLOW CREEK TERMINAL", 952, 699, 1064, 709, 10.5),
        run("EAST PIPE RACK (BAY 3)", 950, 711, 1066, 721, 10.5),
        run("STEEL FRAMING PLAN", 962, 723, 1056, 733, 10.5),
        run("HC2-31-STL-PR3-0020-014", 911, 755, 1048, 767, 12.4),
    ]
    parser = read_titleblock(runs, repeated={"harlowcreekterminal"})
    assert parser.meta.title == "EAST PIPE RACK (BAY 3) STEEL FRAMING PLAN"


def test_title_lines_cut_in_two_are_joined_and_a_misspelt_label_ends_the_block():
    """A title line read as two pieces on one row is one line, and a misspelt "DRAWING NO." label
    under the stack closes the title instead of joining it."""
    runs = [
        run("TITLE", 930, 703, 942, 711, 10.5),
        run("HARLOW CREEK", 952, 707, 1090, 717, 10.5),
        run("STRUCTURAL", 1000, 721, 1060, 731, 10.5),
        run("TAK210-07B -", 952, 735, 1026, 745, 10.5),
        run("PLAN & DETAILS", 1030, 735, 1114, 745, 10.5),
        run("DRAWNG NO.", 930, 749, 990, 758, 10.5),
        run("HC2-31-STL-07-0044-003", 930, 763, 1074, 776, 10.5),
    ]
    title = read_titleblock(runs).meta.title
    assert "TAK210-07B - PLAN & DETAILS" in title
    assert "DRAWNG" not in title


def test_a_title_strip_written_up_the_side_is_read_beside_its_label():
    """In a right-hand strip lettered upward, the title label and its value are vertical runs and the
    value sits in the next column; rotated text that lost its spaces is split into drafting words."""
    up = (0.0, -1.0)
    runs = [
        run("DRAWINGTITLE:", 1178, 424, 1188, 489, 10, direction=up),
        run("ROOFFRAMINGPLAN", 1191, 355, 1206, 474, 15, direction=up),
        run("DRAWING NO.", 1136, 705, 1186, 717, 12),
        run("S-3.2", 1141, 730, 1197, 750, 20),
    ]
    parser = read_titleblock(runs)
    assert parser.meta.title == "ROOF FRAMING PLAN"
    assert parser.meta.number == "S-3.2"


def test_a_tiny_caption_beside_the_title_label_is_not_the_title_value():
    """Two small captions on one row ("DRAWING TITLE :", "PROJECT NUMBER :"): the title is the line
    under the first caption, not the caption beside it."""
    runs = [
        run("DRAWING TITLE  :", 885, 704, 907, 707, 3.2),
        run("PROJECT  NUMBER  :", 1024, 704, 1048, 707, 3.2),
        run("BRACING DETAILS", 889, 711, 975, 721, 9.7),
        run("S402", 1098, 712, 1134, 728, 15.5),
    ]
    assert read_titleblock(runs).meta.title == "BRACING DETAILS"


def test_a_title_label_read_with_a_space_in_it_still_gives_its_value():
    """A label a reader split ("TITL E:") is still the title label: the line under it is the title."""
    runs = [
        run("TITL E:", 2330, 1305, 2348, 1313, 7.9),
        run("ROOF FRAMING PLAN", 2341, 1338, 2530, 1358, 19.6),
        run("S301", 2446, 1598, 2486, 1638, 28.4),
        run("DESIGN:", 2330, 1401, 2355, 1409, 7.9),
    ]
    assert read_titleblock(runs, width=2592, height=1728).meta.title == "ROOF FRAMING PLAN"


def test_an_unlabelled_stack_in_a_scanned_block_gives_its_last_line_as_the_title():
    """With no title label, a scanned block's stack reads company, town, title: the title is the
    last line of the stack, even when the same title repeats on most sheets."""
    runs = scanned_block("SECTIONS AND DETAILS")
    repeated = {"larkspurfabrication", "harlowcreekmanitoba", "sectionsanddetails"}
    assert read_titleblock(runs, repeated=repeated).meta.title == "SECTIONS AND DETAILS"


def test_a_subject_caption_marks_the_title_like_a_title_label():
    """Some owners caption the title cell "SUBJECT": the line under it is the title."""
    runs = [
        run("SUBJECT", 885, 704, 915, 712, 8.0),
        run("STAIR FRAMING DETAILS", 889, 716, 1010, 728, 10.5),
        run("S402", 1098, 712, 1134, 728, 15.5),
    ]
    assert read_titleblock(runs).meta.title == "STAIR FRAMING DETAILS"


# --- repairs to a title read from a scan ----------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "title"),
    [
        ("BEAMSCHEDULE", "BEAM SCHEDULE"),
        ("GIRDERBRIDGE", "GIRDER BRIDGE"),
        ("GENERAL NOTES, TYPICALSECTIONS AND SCHEDULES", "GENERAL NOTES, TYPICAL SECTIONS AND SCHEDULES"),
        ("ROOF PLANAND MEZZANINE FRAMING DETAIL", "ROOF PLAN AND MEZZANINE FRAMING DETAIL"),
        ("NOTES, SITE PLANAND LAYOUT", "NOTES, SITE PLAN AND LAYOUT"),
        ("COVERPAGE", "COVER PAGE"),
    ],
)
def test_words_a_scan_glued_together_are_split_into_drafting_words(read, title):
    """A scan drops spaces; a run-together word is split when it breaks completely into title words."""
    assert split_glued_title(read) == title


@pytest.mark.parametrize("read", ["QXVKPLAN", "LARKSPURFALLSDEPOT"])
def test_a_glued_word_not_fully_explained_by_drafting_words_is_left_as_read(read):
    """A place or company name must never be cut up because part of it looks like a title word."""
    assert split_glued_title(read) == read


@pytest.mark.parametrize(
    ("read", "title"),
    [
        ("FRAMINGPLAN&SCHEDULES", "FRAMING PLAN & SCHEDULES"),
        ("ELEVATIONS&SECTIONS", "ELEVATIONS & SECTIONS"),
        ("3RDFLOORFRAMINGPLAN", "3RD FLOOR FRAMING PLAN"),
    ],
)
def test_lost_spaces_round_an_ampersand_or_after_an_ordinal_are_restored(read, title):
    """ "A&B" and "2NDFLOOR" are spaced the way they were lettered."""
    assert split_glued_title(read) == title


@pytest.mark.parametrize(
    ("read", "title"),
    [
        ("BASE PLATE DETAI1S", "BASE PLATE DETAILS"),
        ("TYPICAL 5ECTIONS", "TYPICAL SECTIONS"),
        ("2D NORTH BRACING W250", "2D NORTH BRACING W250"),
    ],
)
def test_a_digit_read_for_a_letter_is_mended_only_onto_a_drafting_word(read, title):
    """ "5ECTIONS" is a title word with one letter misread; a size or a view name with real digits is
    left alone."""
    assert fix_title_digits(read) == title


# --- stray labels joined to a title ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "title"),
    [
        ("PLATFORM FRAMING PLAN Drawlng No.", "PLATFORM FRAMING PLAN"),
        ("HANDRAIL POST SCHEDULE SHEET", "HANDRAIL POST SCHEDULE"),
        ("STAIR TREAD DETAILS 22-P-A04PUMP SHELTER SHEFTREV", "STAIR TREAD DETAILS 22-P-A04PUMP SHELTER"),
        ("ANCHOR BOLT PLAN Drawimg No.", "ANCHOR BOLT PLAN"),
        ("PLATFORM FRAMING DETAILS AREA UNIT NO ORIG", "PLATFORM FRAMING DETAILS"),
        ("BRACING CONNECTIONS SHEET PLANT AREA NTS", "BRACING CONNECTIONS"),
        ("LADDER CAGE PLAN AND ISOMETRIC CLENTREGIONPROJCT", "LADDER CAGE PLAN AND ISOMETRIC"),
        ("SECTION VIEW AREAUNIT NOORIGGRPCODE SERIAL", "SECTION VIEW AREAUNIT"),
        ("AREAUNIT NOORIGGRPCODE", ""),
    ],
)
def test_field_labels_a_scan_joined_to_the_end_of_a_title_are_trimmed(read, title):
    """Label words under the title cell ("Drawing No.", "SHEET", "REV", a row of unit and group labels)
    get joined to the title by a scan, sometimes misread or glued: they are cut off its end."""
    assert trim_stray_labels(read) == title


@pytest.mark.parametrize(
    "title",
    [
        "TYPICAL DETAILS SHEET 2 OF 3",
        "BRACKET DETAIL",
        "STRUCTURAL GENERAL NOTES",
        "BOILER PLANT AREA PLAN",
        "SCALE HOUSE PLAN",
        "NORTH, SOUTH ELEVATIONS PLAN",
    ],
)
def test_a_title_made_of_drafting_words_is_not_trimmed(title):
    """A drafting word closing a title ("NOTES", "PLAN") is the title, whatever label it resembles;
    a sheet-of-set suffix stays for the caller to remove."""
    assert trim_stray_labels(title) == title


@pytest.mark.parametrize(
    ("read", "title"),
    [
        ("5CALE NTS DESIGNEO N/A TANK FARM FOUNDATIONS", "TANK FARM FOUNDATIONS"),
        ("LARKSPUR FALLS, MANITOEA PIPE RACK LOCATION PLAN", "PIPE RACK LOCATION PLAN"),
        ("ORPORATION ANCHOR BOLT PLAN", "ANCHOR BOLT PLAN"),
    ],
)
def test_a_label_row_address_or_company_end_in_front_of_a_title_is_trimmed(read, title):
    """A scan can run the row before the title into it: a row of field labels, the site address
    (town, misread region) or the cut end of a company line."""
    assert trim_stray_labels(read) == title


def test_a_sheet_of_set_suffix_and_a_revision_code_are_recognised():
    """ "SHEET 1 OF 2" after a title is page furniture; a dotted code ("0.A.1", zero read as "O") is a
    revision code, never a title word."""
    assert RE_SHEET_OF.sub("", "TYPICAL DETAILS SHEET 2 OF 3") == "TYPICAL DETAILS"
    assert RE_REV_CODE.match("O.B.B") and RE_REV_CODE.match("0.C.2")
    assert not RE_REV_CODE.match("PLAN")


def test_a_misspelt_field_label_line_is_recognised_as_a_label():
    """Short lines close to a known label ("PLANT AREA", "EQUIP NO") are labels, so they are not
    sorted into a stack of title lines."""
    assert fuzzy_label_line("PLAHT AREA") and fuzzy_label_line("EQUIP NO")
    assert not fuzzy_label_line("FRAMING PLAN")


# --- what is, and is not, a title -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "SURVEY PLAN",
        "ANCHOR BOLT PLAN",
        'ISOMETRIC FOR 14-CW-0310-8"-CS3 (PUMP-B INLET)',
    ],
)
def test_a_line_naming_a_drawing_type_can_be_a_title(text):
    """A title names the drawing type; an inch mark inside a line designation does not make it a note."""
    assert plausible_title(text)


def test_bridge_words_and_a_cover_page_count_as_title_words():
    """Title vocabulary covers bridge drawings and cover pages, in capitals or not."""
    assert RE_TITLE_WORD.search("TWO-SPAN GIRDER BRIDGE")
    assert plausible_title("Steel Cover Sheet", one_word_ok=True)


@pytest.mark.parametrize(
    "text",
    [
        "CHECK OATE03MAR21",  # a field row with its date glued on
        "SCALE AS SHOWN",
        "MAINTENANCE DEPT.",  # a sign-off row
        'NOTE 8" CLEAR MIN',  # a dimension note
        "ISSUEDFORTENDER",  # an issue stamp read without spaces
        "as shown, refer to sections for sizes.",  # a sentence
        "NO WORK TO PROCEED WITHOUT CONSENT",  # boilerplate
        "OMITTED FROM THIS SHEET",
        "BOLTED ON SITE INSTEAD OF WELDED",
        "TENDER UNIT RATE MAY12",
        "FOR SHOP 3307 USE ONLY",  # a stamp
        "SHEET RASTERISED",  # a stamp
        "REVISIN DESCRPTION",  # the revision table's caption, misread
        "Contract No.",  # a caption ending in "No."
        "3 OF 7",  # a sheet count
        "HARLOW CREEK, MANITOBA",  # an address line
    ],
)
def test_title_block_furniture_is_not_a_title(text):
    """Field rows, stamps, captions, sentences, boilerplate and address lines are never a title."""
    assert not plausible_title(text)


@pytest.mark.parametrize(
    "text",
    [
        "DESCRIPTION",
        "DESCRPTION",
        "DESCRlPTION",
        "TlTLE",
        "PRINTED",
        "NUMBER",
        "PREVIOUS DRAWING",
        "PREVOUS SHEET",
        "K. TORVALD",
    ],
)
def test_a_single_caption_word_or_a_sign_off_name_is_not_a_title(text):
    """Even where one capitals word may be a title (beside the sheet number), a column header, a
    caption (misread or not) or an initial-and-surname is not."""
    assert not plausible_title(text, one_word_ok=True)
