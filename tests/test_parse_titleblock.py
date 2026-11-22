"""Title block reading on hand-built sheets: sheet number, sheet title, labelled fields, project
name, sheet scale and project location.

Every sheet here is a handful of invented text runs placed in the bottom strip of a 1224 x 792 page
(the title block band starts at 82% of the height)."""

from __future__ import annotations

import pytest

from drawing_reader.parse import SheetParser
from drawing_reader.parse.location import find_city_region
from drawing_reader.parse.sheet_numbers import RE_SHEET_NO
from drawing_reader.parse.titles import plausible_title
from support import index_sheets, make_run, make_sheet


def _run(text, x0, y0, x1, y1, size, conf=1.0):
    return make_run(text, x0, y0, size, x1=x1, y1=y1, conf=conf)


def _title_block(runs, **sheet_extra):
    """The parser of one sheet after the title block rule has run."""
    parser = SheetParser(make_sheet(runs, **sheet_extra))
    parser.parse_titleblock(set())
    return parser


def _locations(*runs):
    parser = SheetParser(make_sheet(runs))
    parser.parse_location()
    return [f for f in parser.facts if f.attrs.get("field") == "Location"]


# --- sheet number ---------------------------------------------------------------------------------


@pytest.mark.parametrize("number", ["A.7", "C.2.4", "E.6.1.3", "D.1.4.6.2", "D.1.4.6.12", "D.1.4.8.3"])
def test_dotted_sheet_number_may_have_up_to_five_segments(number):
    """A dotted numbering convention: one letter, then up to five dot-separated numeric segments."""
    assert RE_SHEET_NO.match(number)


@pytest.mark.parametrize("text", ["3.4", "7500", "C.2.4.6.8.1.3", "D.1.4.6.2.3.3"])
def test_bare_numbers_and_overlong_dotted_chains_are_not_sheet_numbers(text):
    """A decimal, a dimension, or a chain of more than five segments is not a sheet number."""
    assert not RE_SHEET_NO.match(text)


def test_segmented_document_number_is_the_sheet_number_only_without_a_sheet_style_number():
    """A long segmented document number names the sheet only when no short sheet-style number exists."""
    alone = _title_block(
        [_run("KM-31-CIV-02-240-07", 900, 700, 1090, 722, 14), _run("DATE: 2031-03-14", 900, 728, 1000, 738, 8)]
    )
    assert alone.meta.number == "KM-31-CIV-02-240-07"
    both = _title_block([_run("S-204", 900, 700, 980, 722, 14), _run("KM-31-CIV-02-240-07", 900, 728, 1090, 738, 8)])
    assert both.meta.number == "S-204"


def test_document_number_cut_in_two_is_joined():
    """A long number split into two runs on one row ("AB12-" + "-S-3050-2") reads as one number."""
    parser = _title_block([_run("QF482-", 900, 700, 950, 715, 12), _run("-S-3050-2", 952, 700, 1030, 715, 12)])
    assert parser.meta.number == "QF482-S-3050-2"


def test_half_a_document_number_with_no_neighbour_is_not_a_number():
    """A cut-off fragment with nothing to join stays out: the sheet keeps its page placeholder."""
    parser = _title_block([_run("QF482-", 900, 700, 950, 715, 12), _run("NOTES", 700, 700, 750, 715, 12)])
    assert parser.meta.number == "P1"


# --- sheet title ----------------------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["480", "K"])
def test_title_is_never_a_bare_number_or_a_single_letter(junk):
    """A dimension or a stray grid letter beside the sheet number is not the sheet title."""
    parser = _title_block([_run("S-201", 80, 700, 150, 722, 22), _run(junk, 170, 700, 215, 720, 20)])
    assert parser.meta.number == "S-201"
    assert parser.meta.title == ""


def test_title_is_the_large_text_beside_the_sheet_number():
    """The large text next to the sheet number is the title when it names a drawing."""
    parser = _title_block([_run("S-201", 80, 700, 150, 722, 22), _run("PLATFORM PLAN", 170, 700, 330, 720, 20)])
    assert parser.meta.title == "PLATFORM PLAN"


def test_labelled_sheet_title_replaces_the_proximity_guess():
    """A value under a "Sheet Title" label wins over the large text nearest the number, and only one
    sheet-title fact is left for the answer rules to cite."""
    parser = _title_block(
        [
            _run("S-020", 80, 700, 150, 722, 22),
            _run("PROJECT 70314455", 170, 700, 370, 720, 22),
            _run("Sheet Title", 600, 676, 655, 685, 8),
            _run("FRAMING DETAILS", 665, 676, 760, 686, 9),
        ]
    )
    assert parser.meta.title == "FRAMING DETAILS"
    titles = [f.value for f in parser.facts if f.attrs.get("field") == "sheet_title"]
    assert titles == ["FRAMING DETAILS"]


def test_title_written_on_two_lines_is_joined():
    """A title stacked on two lines beside the number is read whole; large text far away is not added."""
    parser = _title_block(
        [
            _run("S30-02", 1100, 720, 1165, 742, 20),
            _run("MEZZANINE AND ROOF", 900, 698, 1085, 718, 18),
            _run("BRACING ELEVATIONS", 900, 720, 1080, 740, 18),
            _run("ISSUED", 900, 880, 975, 900, 18),
        ]
    )
    assert parser.meta.title == "MEZZANINE AND ROOF BRACING ELEVATIONS"


def test_title_printed_twice_is_not_doubled():
    """The same title line drawn twice (an overprint) appears once in the title."""
    parser = _title_block(
        [
            _run("S-305", 1100, 720, 1165, 742, 20),
            _run("BEAM & BRACE SCHEDULE", 880, 698, 1085, 718, 18),
            _run("BEAM & BRACE SCHEDULE", 880, 720, 1085, 740, 18),
        ]
    )
    assert parser.meta.title == "BEAM & BRACE SCHEDULE"


def test_title_is_found_by_its_vocabulary_when_a_logo_and_the_number_are_larger():
    """A big logo and a big sheet number raise the "large text" bar above the real, smaller title
    lines; the lines still read as the title because they use drawing-title words."""
    parser = _title_block(
        [
            _run("norvale", 900, 690, 1050, 732, 28),
            _run("S214", 990, 738, 1060, 756, 40),
            _run("THIRD FLOOR", 900, 668, 985, 681, 12),
            _run("PLAN", 900, 683, 940, 696, 12),
        ]
    )
    assert parser.meta.number == "S214"
    assert parser.meta.title == "THIRD FLOOR PLAN"


@pytest.mark.parametrize(
    "text",
    [
        "Printed copies are not controlled; refer to the electronic file for the current issue",
        "NORVALE LTD",
        "norvale",
        "ISSUED FOR CONSTRUCTION",
        "AREA NO.",
        "TOP OF PIERS 84'-7 U.N.O.",
        "CLIEMT DWG N0.",
        "REF TO PREVIOUS",
        "4) CRANE RAIL CLIPS MUST ALLOW ADJUSTMENT",
        "Page 2 of 6",
        "AS SHOWN",
    ],
)
def test_footers_company_lines_notes_and_labels_are_not_titles(text):
    """A footer sentence, a company line, an issue stamp, a field label, a note or a scale is no title."""
    assert not plausible_title(text)


@pytest.mark.parametrize(
    "text",
    [
        "ELEVATIONS AND DETAILS",
        "Framing Plan",
        "GENERAL NOTES & TYPICAL DETAILS",
        "FLOOR FRAMING PLANS, SECTIONS & SCHEDULES",
    ],
)
def test_drawing_type_phrases_are_titles(text):
    """A phrase naming a drawing type reads as a title in capitals or in mixed case."""
    assert plausible_title(text)


def test_one_word_title_needs_permission_and_vowels():
    """A single capitals word is a title only beside the sheet number, and only when it reads as a word."""
    assert plausible_title("HANDRAILS", one_word_ok=True)
    assert not plausible_title("HANDRAILS")
    assert not plausible_title("QTRM407", one_word_ok=True)


# --- labelled fields ------------------------------------------------------------------------------


def test_label_directly_over_the_sheet_number_takes_no_value():
    """A "Checked by" label that sits over the sheet-number cell must not take the number as its value."""
    parser = _title_block([_run("Checked by", 1000, 668, 1045, 677, 8), _run("S.2.7", 1002, 680, 1045, 691, 10)])
    assert "Checked By" not in parser.meta.fields


def test_placeholder_values_are_rejected_and_real_values_kept():
    """A dash or a template word left in an unfilled cell is not a value; a filled cell is read."""
    parser = _title_block(
        [
            _run("Rev", 900, 670, 920, 679, 8),
            _run("-", 930, 670, 936, 679, 8),
            _run("Drawn by", 900, 692, 940, 701, 8),
            _run("Author", 950, 692, 985, 701, 8),
            _run("Date", 900, 714, 920, 723, 8),
            _run("2031-03-14", 930, 714, 1000, 723, 8),
        ]
    )
    assert "Rev" not in parser.meta.fields
    assert "Drawn By" not in parser.meta.fields
    assert parser.meta.fields.get("Date") == "2031-03-14"


def test_title_block_widens_left_when_the_scanned_box_edge_is_an_inner_divider():
    """On a scan the box edge found in the raster can be a divider inside the title block; when
    almost nothing is right of it, the whole bottom-right area is read instead."""
    runs = [
        _run("ENGINEER", 1130, 720, 1185, 732, 8),
        _run("C27.04-5D-00163", 740, 745, 870, 758, 12),
        _run("PIER LAYOUT PLAN", 740, 700, 870, 713, 10),
        _run("LS3", 150, 720, 172, 732, 6),
    ]
    parser = _title_block(runs, titleblock_x=1080.0)
    assert parser.meta.number == "C27.04-5D-00163"
    assert parser.meta.title == "PIER LAYOUT PLAN"


# --- project name ---------------------------------------------------------------------------------


def test_project_name_leaves_out_a_number_repeated_on_every_sheet():
    """The page total of "sheet 3 of 3" repeats on every sheet like the project name does, but a
    purely numeric text is never part of the name."""
    sheets = [
        make_sheet(
            [
                _run("HARLOW CREEK PUMP HOUSE", 80, 700, 420, 724, 20),
                _run("3", 450, 700, 470, 724, 20),
                _run(f"S-0{i}", 500, 700, 570, 724, 20),
            ]
        )
        for i in range(1, 4)
    ]
    assert index_sheets(*sheets).project.get("name") == "HARLOW CREEK PUMP HOUSE"


# --- sheet scale ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "scale"),
    [
        ("SCALE: 1:40", "1:40"),
        ("Scole: 1:200", "1:200"),
        ("SCALE: 3/8′=1′0*", '3/8"=1\'0"'),
        ("N.T.S.", "NTS"),
        ("SCALE: AS NOTED", "AS NOTED"),
    ],
)
def test_sheet_scale_is_read_from_one_run_in_scanned_spellings(text, scale):
    """A scale stated in one run is the sheet scale; on a scan a misread label and odd foot and inch
    marks are brought to one spelling."""
    parser = _title_block([_run(text, 900, 720, 1010, 733, 10, conf=0.9)])
    parser.parse_sheet_scale()
    assert parser.meta.scale == scale


def test_sheet_scale_ignores_sentences_that_use_the_word():
    """ "DO NOT SCALE" and "REMOVE MILL SCALE" are prose about scaling, not a scale statement."""
    parser = _title_block(
        [_run("DO NOT SCALE THIS DRAWING.", 900, 720, 1070, 733, 10), _run("REMOVE MILL SCALE", 900, 745, 990, 758, 10)]
    )
    parser.parse_sheet_scale()
    assert parser.meta.scale == ""


def test_two_different_view_scales_give_no_sheet_scale():
    """Two views with two scales: the sheet has no single scale, the views carry their own."""
    parser = _title_block([_run("SCALE: 1:30", 150, 200, 250, 213, 10), _run("SCALE: 1:75", 500, 200, 600, 213, 10)])
    parser.parse_sheet_scale()
    assert parser.meta.scale == ""


# --- project location -----------------------------------------------------------------------------


def test_street_address_is_joined_to_the_city_line_below_it():
    """A street address with "City, Province" on the next line reads as one location, and the city
    line is also kept on its own."""
    found = _locations(
        _run("4718 ORCHARD ROAD", 60, 150, 250, 165, 14), _run("LARKSPUR FALLS, MANITOBA", 60, 168, 290, 183, 14)
    )
    assert [f.value for f in found] == ["4718 ORCHARD ROAD, LARKSPUR FALLS, MANITOBA", "LARKSPUR FALLS, MANITOBA"]
    assert [f.attrs["loc_kind"] for f in found] == ["address", "city_province"]


@pytest.mark.parametrize("text", ["16MM CAP PL", "300 EACH WAY", "ALL ANCHORS SHALL, BC"])
def test_plates_spacings_and_filler_words_are_not_locations(text):
    """A plate callout, an "each way" spacing, or a filler word in front of a region code is no place."""
    assert _locations(_run(text, 400, 300, 520, 311, 10)) == []


def test_region_code_closing_the_line_is_accepted_after_a_comma():
    """ "City, XX" at the end of a line is a place."""
    assert find_city_region("LARKSPUR FALLS, MB") == ("LARKSPUR FALLS", "MB")


@pytest.mark.parametrize("tail", [" Z9Z 9Z9", ", CANADA", " 00000"])
def test_region_code_is_accepted_when_a_postal_code_or_country_follows(tail):
    """A code in mid-line still counts when a postal code or the country comes right after it."""
    region = "MT" if tail.strip().isdigit() else "MB"
    assert find_city_region(f"LARKSPUR FALLS, {region}{tail}") == ("LARKSPUR FALLS", region)


@pytest.mark.parametrize(
    "text", ["STAINLESS PLATES, OR EQUAL", "SHIM PACKS, IN SETS OF FOUR", "GALVANIZED BOLTS, ON SITE"]
)
def test_region_code_in_mid_sentence_is_rejected(text):
    """Two-letter codes are also English words ("OR", "IN", "ON"): after a comma inside a sentence
    they do not make the words before them a city."""
    assert find_city_region(text) is None


@pytest.mark.parametrize(
    "text", ["LARKSPUR FALLS, MANITOBA PLANT SITE", "Larkspur Falls, New Brunswick", "LARKSPUR MANITOBA"]
)
def test_region_written_in_full_counts_anywhere_on_the_line(text):
    """A province or state written out is strong evidence, in mid-line and without the comma."""
    place = find_city_region(text)
    assert place is not None and place[1].upper() in {"MANITOBA", "NEW BRUNSWICK"}


def test_city_and_code_without_a_comma_need_a_postal_code():
    """ "City XX" without the comma is a place only when a postal code follows."""
    assert find_city_region("LARKSPUR MB") is None
    assert find_city_region("LARKSPUR MB Z9Z 9Z9") == ("LARKSPUR", "MB")


def test_one_short_word_is_a_city_only_with_a_postal_code():
    """A single word of three or four letters before a region is usually scan junk; a real short
    town name is accepted when a postal code follows the region."""
    assert find_city_region("VOSK, MANITOBA") is None
    assert find_city_region("VOSK, MB") is None
    assert find_city_region("VOSK, MB Z9Z 9Z9") == ("VOSK", "MB")


def test_filler_word_before_a_region_code_is_not_a_city():
    """ "... SHALL, BC" comes from a sentence, not an address."""
    assert find_city_region("ALL ANCHORS SHALL, BC") is None
    assert find_city_region("SEE NOTES, ONTARIO") is None
