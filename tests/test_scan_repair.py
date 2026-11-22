"""Repairs across a scanned set: a sheet number read badly on one sheet is completed from its
siblings or from the set's own drawing list, and a rare member size one character away from a common
one is flagged. Every number here is invented."""

from __future__ import annotations

from drawing_reader.ingest import Document
from drawing_reader.parse.scan_repair import flag_label_misreads, repair_sheet_numbers
from drawing_reader.schema import Index, SheetMeta
from support import make_fact, make_run, make_sheet


def scanned_index(numbers):
    """An OCR-read index with one sheet per number and one note on each (linked to a second note)."""
    idx = Index(doc_id="test", source="made_up.pdf", is_vector=False, from_ocr=True)
    for page, number in enumerate(numbers, 1):
        idx.sheets.append(SheetMeta(page=page, number=number))
        note = make_fact(f"{number}.note.001", "note", "GROUT UNDER BASE PLATES", number)
        note.links = [f"{number}.note.002"]
        idx.facts.append(note)
    return idx


def repaired(numbers):
    """The sheet numbers of a scanned set after the set-level repair."""
    idx = scanned_index(numbers)
    repair_sheet_numbers(idx)
    return [s.number for s in idx.sheets]


def scanned_document(*pages, width=1224.0, height=792.0):
    """A scanned document: each page is a list of (text, x, y, size) read by OCR."""
    sheets = [
        make_sheet([make_run(text, x, y, size, conf=0.95) for text, x, y, size in page], width=width, height=height)
        for page in pages
    ]
    return Document(doc_id="test", source="made_up.pdf", sheets=sheets, is_vector=False, from_ocr=True)


# --- completing a number from its siblings ----------------------------------------------------------


def test_a_document_number_that_lost_its_leading_parts_is_completed_from_its_siblings():
    """Document numbers of one set share their leading parts, so a number that starts partway gets
    the parts nine in ten of the well-formed numbers share; short marks are left alone."""
    numbers = [
        "HC2-31-STL-PR3-0020-016",
        "HC2-31-STL-PR3-0020-021",
        "HC2-31-STL-PR3-0020-022",
        "HC2-31-STL-PR4-0006-007",
        "-31-STL-PR4-0006-002",
        "31-STL-PR5-0006-006",
        "STL-PR4-0006-006",
        "HC2",
        "P12",
    ]
    assert repaired(numbers)[4:] == [
        "HC2-31-STL-PR4-0006-002",
        "HC2-31-STL-PR5-0006-006",
        "HC2-31-STL-PR4-0006-006",
        "HC2",
        "P12",
    ]


def test_facts_follow_a_repaired_sheet_number():
    """A fact's sheet, id and links are renamed with its sheet, so citations still resolve."""
    idx = scanned_index(
        [
            "HC2-31-STL-PR3-0020-016",
            "HC2-31-STL-PR3-0020-021",
            "HC2-31-STL-PR3-0020-022",
            "HC2-31-STL-PR4-0006-007",
            "-31-STL-PR4-0006-002",
        ]
    )
    repair_sheet_numbers(idx)
    fact = idx.facts[4]
    assert fact.sheet == "HC2-31-STL-PR4-0006-002"
    assert fact.id == "HC2-31-STL-PR4-0006-002.note.001"
    assert fact.links == ["HC2-31-STL-PR4-0006-002.note.002"]


def test_a_digit_read_for_the_leading_letter_is_repaired_only_with_a_sibling_of_that_letter():
    """ "0004" among "D001", "S002": the zero is a misread "D", but only because a sibling of the same
    shape starts with "D"; without one the number is left as read."""
    assert repaired(["D001", "S001", "S002", "0004", "P4", "0012", "S003"]) == [
        "D001",
        "S001",
        "S002",
        "D004",
        "P4",
        "D012",
        "S003",
    ]
    assert repaired(["S001", "S002", "S003", "0004"])[3] == "0004"


def test_a_dashed_series_number_whose_letter_was_read_as_a_digit_is_mended_from_its_siblings():
    """ "5-1.2" among "S-1.1", "S-2.1", "S-3": the five is the series letter "S"; a digit whose letter
    no sibling carries stays."""
    assert repaired(["S-1.1", "5-1.2", "S-2.1", "S-3", "5-3.4", "3-7"]) == [
        "S-1.1",
        "S-1.2",
        "S-2.1",
        "S-3",
        "S-3.4",
        "3-7",
    ]


def test_a_badly_read_number_between_two_consecutive_neighbours_takes_the_number_they_imply():
    """Between D003 and D005 a four-character misread is D004, when it is at most two characters
    away from it."""
    numbers = ["D001", "D002", "D003", "DO04", "D005", "D006", "0006", "D008", "S001"]
    assert repaired(numbers) == ["D001", "D002", "D003", "D004", "D005", "D006", "D007", "D008", "S001"]


def test_a_number_its_neighbours_do_not_imply_is_left_as_read():
    assert repaired(["D001", "QRST", "D009"])[1] == "QRST"


def test_neighbours_misread_the_same_way_are_repaired_before_the_gap_between_them():
    """The neighbours are taken as repaired ("0005" is D005), so a run of misreads still closes."""
    numbers = ["D001", "D002", "0003", "DO04", "0005", "0006", "0006", "0008", "D009"]
    assert repaired(numbers)[2:8] == ["D003", "D004", "D005", "D006", "D007", "D008"]


# --- repairs that read the pages --------------------------------------------------------------------


def test_a_sheet_numbered_by_the_repeated_project_id_takes_the_digits_in_its_block_foot():
    """Among sheets numbered by bare digits, a sheet that got the project id every sheet repeats (or
    a page fallback) takes the digits printed in the corner of its own block."""
    doc = scanned_document(
        [("301", 764, 557, 6.4)],
        [("302", 764, 557, 6.4), ("K0042C-0031", 700, 558, 5.6)],
        [("303", 764, 557, 6.4)],
        width=792.0,
        height=612.0,
    )
    idx = scanned_index(["301", "K0042C-0031", "K0042C-0031"])
    repair_sheet_numbers(idx, doc)
    assert [s.number for s in idx.sheets] == ["301", "302", "303"]


def test_a_number_that_lost_its_dashes_takes_the_shape_of_the_sets_own_drawing_list():
    """The list of drawings printed on the sheets gives the number's shape, dashes included: a read
    with the same letters and digits gets its dashes back ("=" read for a dash too), and a short mark
    among sheets that all carry the long number falls back to its page."""
    listed = [(f"F420-3107-08K-00{n}-02", 200, 600 + 8 * i, 6.5) for i, n in enumerate((41, 42, 43))]
    doc = scanned_document(listed, listed, listed, listed)
    idx = scanned_index(["F4203107-08K-0017-02", "F4203107-08K0018-02", "F420-3107-08K=0019-02", "M12"])
    repair_sheet_numbers(idx, doc)
    assert [s.number for s in idx.sheets] == [
        "F420-3107-08K-0017-02",
        "F420-3107-08K-0018-02",
        "F420-3107-08K-0019-02",
        "P4",
    ]


# --- member sizes -----------------------------------------------------------------------------------


def test_a_rare_member_size_one_character_off_a_common_one_is_flagged_not_changed():
    """A size seen once beside twenty of a size one character away is probably that size misread:
    it is flagged with the likely size and keeps its value; an unrelated rare size is not flagged."""
    labels = [make_fact(f"S-101.label.{i:03d}", "label", "W250X33", "S-101", section="W250X33") for i in range(20)]
    labels.append(make_fact("S-101.label.100", "label", "W250X38", "S-101", section="W250X38"))
    labels.append(make_fact("S-101.label.101", "label", "W410X54", "S-101", section="W410X54"))
    idx = Index(doc_id="test", source="made_up.pdf", is_vector=False, from_ocr=True, facts=labels)
    flag_label_misreads(idx)
    assert {f.value: f.attrs["suspect_of"] for f in idx.facts if "suspect_of" in f.attrs} == {"W250X38": "W250X33"}
    assert sorted({f.value for f in idx.facts}) == ["W250X33", "W250X38", "W410X54"]
