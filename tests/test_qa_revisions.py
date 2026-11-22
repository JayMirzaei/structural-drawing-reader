"""Revision questions: scoping to a sheet or to a revision code, counting, history, and saying
plainly when the revision asked about does not exist. Also how a written sheet reference is matched
to a real sheet number.

The example set issues every sheet as A, B (lettered, before issue) and 0; only S-301 has a later
revision 1."""

from __future__ import annotations

import pytest

from drawing_reader.parse.sheet_numbers import sheet_ref_matches
from drawing_reader.qa import answer, tokens
from drawing_reader.qa.rules.titleblock import rule_revisions

OTHER_SHEETS = ("S-001", "S-101", "S-201", "S-401")


def test_latest_revision_is_scoped_to_the_named_sheet(platform):
    """'Latest revision on <sheet>' gives that sheet's row, not the latest of every sheet."""
    a = answer("What is the latest revision on S-301?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.sheets == ["S-301"]
    assert a.fact_ids == ["S-301.revision.004"]
    assert "rev 1" in a.text and "REVISED ANCHOR ROD SIZE" in a.text
    for other in OTHER_SHEETS:
        assert other not in a.text


def test_revision_history_prints_every_row_it_cites(platform):
    """A history question cites every row of the sheet and prints each of them, so the answer text
    and its evidence agree."""
    a = answer("Show the revision history of S-301", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.sheets == ["S-301"]
    assert len(a.fact_ids) == 4
    for code in ("rev A", "rev B", "rev 0", "rev 1"):
        assert code in a.text


def test_revision_history_shows_the_named_sheet_only(platform):
    a = answer("What is the revision history of S-201?", platform, llm=None)
    assert a.method == "rule:revisions"
    for date in ("2030-02-04", "2030-03-26", "2030-05-08"):
        assert date in a.text
    assert "S-301:" not in a.text and "REVISED ANCHOR ROD SIZE" not in a.text


def test_a_revision_code_is_looked_up_on_every_sheet(platform):
    """'When was revision B issued?' finds the B row of each sheet, not the latest row per sheet
    (which never mentions B)."""
    a = answer("When was revision B issued?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert sorted(a.sheets) == ["S-001", "S-101", "S-201", "S-301", "S-401"]
    assert len(a.fact_ids) == 5
    assert "2030-03-26" in a.text
    for other_date in ("2030-02-04", "2030-05-08", "2030-06-19"):
        assert other_date not in a.text


def test_a_revision_code_leaves_out_sheets_that_do_not_have_it(platform):
    """Only one sheet was revised after issue: 'rev 1' lists that sheet and no other."""
    a = answer("What changed in rev 1?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.fact_ids == ["S-301.revision.004"]
    assert "S-301:" in a.text and "REVISED ANCHOR ROD SIZE" in a.text
    for other in OTHER_SHEETS:
        assert f"{other}:" not in a.text


def test_a_revision_code_on_a_named_sheet(platform):
    """A code and a sheet together select one row."""
    a = answer("What was revision 1 for on S-301?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.fact_ids == ["S-301.revision.004"]
    assert "REVISED ANCHOR ROD SIZE" in a.text

    b = answer("When was revision 0 of S-201 issued?", platform, llm=None)
    assert b.method == "rule:revisions"
    assert b.fact_ids == ["S-201.revision.003"]
    assert "ISSUED FOR CONSTRUCTION" in b.text and "2030-05-08" in b.text
    assert "S-101:" not in b.text and "S-301:" not in b.text


def test_a_code_missing_from_the_named_sheet_lists_the_rows_that_exist(platform):
    """A real revision code that the named sheet does not have is reported as missing, with the
    codes the sheet does have. Nothing else from that sheet is put in its place."""
    a = answer("Rev 1 on S-101?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.text == "No revision 1 found on S-101 (rows found: A, B, 0)."
    assert a.confidence == 0.8
    assert a.fact_ids == []

    b = answer("What was revision 1 on S-401 for?", platform, llm=None)
    assert b.text.startswith("No revision 1 found on S-401")


def test_how_many_revisions_counts_the_rows_of_the_named_sheet(platform):
    """'How many revisions' wants a count, not the latest row."""
    a = answer("How many revisions does S-301 have?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.text == "4 revision(s) on S-301."
    assert len(a.fact_ids) == 4
    assert a.sheets == ["S-301"]


def test_revision_rule_declines_a_sheet_that_is_not_in_the_set(platform):
    """A sheet-shaped word that is not one of the set's sheets must not get the answer for all
    sheets."""
    q = "what is the latest revision on s-909?"
    assert rule_revisions(q, tokens(q), platform) is None


def test_the_plural_s_of_revisions_is_not_read_as_a_revision_code(platform):
    """A set with lettered codes makes 'revisions' look like 'revision S'. Only a code that exists
    in the index is trusted, so the count question is not answered with 'no revision s found'."""
    a = answer("How many revisions does S-101 have?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.text == "3 revision(s) on S-101."


def test_a_lettered_code_matches_whatever_its_case(platform):
    """'rev b' and 'rev B' are the same lettered pre-issue revision."""
    for q in ("What is rev B on S-101?", "what is rev b on S-101?"):
        a = answer(q, platform, llm=None)
        assert a.method == "rule:revisions"
        assert a.fact_ids == ["S-101.revision.002"]
        assert "ISSUED FOR APPROVAL" in a.text
        assert "ISSUED FOR REVIEW" not in a.text


def test_a_letter_that_is_not_a_code_of_the_set_is_not_reported_missing(platform):
    """A captured single letter is trusted as a revision code only when the set uses it. 'Rev C'
    here must not give a confident 'no revision C found'."""
    a = answer("What is rev C on S-101?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert "No revision C found" not in a.text and "No revision c found" not in a.text


def test_an_unknown_revision_number_is_reported_missing(platform):
    """A revision number that exists nowhere in the set gets 'not found', never the latest revision
    as if no number had been asked for."""
    a = answer("What is revision 99 on S-101?", platform, llm=None)
    assert a.method == "rule:revisions"
    assert a.text.startswith("No revision 99 found on S-101")

    b = answer("What changed in rev 99?", platform, llm=None)
    assert b.method == "rule:revisions"
    assert b.text.startswith("No revision 99 found")


def test_latest_revision_of_each_sheet(platform):
    """The plain question (no sheet, no code, no history word) gives one row per sheet, and a
    numeric revision outranks the lettered ones issued before it."""
    a = answer("What is the latest revision on each sheet?", platform, llm=None)
    assert a.method == "rule:revisions"
    lines = a.text.splitlines()
    assert lines[0] == "Revision status per sheet:"
    assert lines[1] == "- S-001: latest is rev 0 “ISSUED FOR CONSTRUCTION” 2030-05-08 (3 rows)"
    assert lines[2] == "- S-101: latest is rev 0 “ISSUED FOR CONSTRUCTION” 2030-05-08 (3 rows)"
    assert lines[3] == "- S-201: latest is rev 0 “ISSUED FOR CONSTRUCTION” 2030-05-08 (3 rows)"
    assert lines[4] == "- S-301: latest is rev 1 “REVISED ANCHOR ROD SIZE” 2030-06-19 (4 rows)"
    assert lines[5] == "- S-401: latest is rev 0 “ISSUED FOR CONSTRUCTION” 2030-05-08 (3 rows)"
    assert a.fact_ids == [
        "S-001.revision.003",
        "S-101.revision.003",
        "S-201.revision.003",
        "S-301.revision.004",
        "S-401.revision.003",
    ]


def test_revision_date_stops_at_the_date_column(platform):
    """A revision row's date is the date printed in its row, without the title-block labels that sit
    at the same height further right (the fourth row of this sheet is level with DRAWN BY)."""
    assert platform.get("S-301.revision.004").attrs["date"] == "2030-06-19"


@pytest.mark.parametrize(
    ("written", "real", "same"),
    [
        ("S201", "S-201", True),  # a note drops the dash of the title-block number
        ("A-501", "A-501", True),
        ("S40", "S40-02", True),  # a note names the series, the sheet is one of that series
        ("S20", "S-201", False),
        ("S-202", "S-201", False),
    ],
)
def test_written_sheet_reference_matches_the_real_sheet_number(written, real, same):
    """Notes write sheet numbers loosely: without the dash, or as the prefix of a numbered series."""
    assert sheet_ref_matches(written, real) is same
