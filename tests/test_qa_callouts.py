"""Detail callouts and written detail references: how they are parsed from note text and how the
callout rule answers 'where is detail N used' and 'how many callouts reference a sheet'."""

from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.qa import answer
from support import make_fact, make_index, make_run, make_sheet


def callout(fid, sheet, detail, target):
    return make_fact(
        fid, "callout", f"{detail}/{target}", sheet, detail=detail, target_sheet=target, target_in_set=True
    )


def note_reference(fid, sheet, detail, target, text):
    return make_fact(
        fid,
        "reference",
        f"{detail}/{target}",
        sheet,
        detail=detail,
        target_sheet=target,
        context=text,
        target_in_set=True,
    )


def detail_references(*lines):
    """Parse loose text lines and return the (detail, sheet) pairs of the references found in them."""
    runs = [make_run(text, 50, 100 + 20 * i, block=i) for i, text in enumerate(lines)]
    parser = SheetParser(make_sheet(runs))
    parser.parse_remaining_text()
    return [(f.attrs["detail"], f.attrs["target_sheet"]) for f in parser.facts if f.kind == "reference"]


# ---- parsing ------------------------------------------------------------------------------------
def test_written_detail_over_sheet_reference_becomes_a_reference_fact():
    """A note that writes 'SEE DETAIL 6/S502' (number over sheet id, inline) is a cross-reference
    like a drawn bubble; a fraction or a scale ratio in the same text is not."""
    found = detail_references(
        "EMBED PLATE - SEE DETAIL 6/S502",
        "STIFFENERS - SEE SECT. B2/S604",
        "SEE ELEV.2/S203",
        'RODS 3/4" DIA',
        "SCALE 1 : 25",
    )
    assert sorted(found) == [("2", "S203"), ("6", "S502"), ("B2", "S604")]


def test_written_detail_reference_with_a_dashed_sheet_number():
    """The same inline convention with a dashed sheet number names the same kind of target."""
    assert detail_references("EMBED PLATE - SEE DETAIL 6/S-502") == [("6", "S-502")]


# ---- answering ----------------------------------------------------------------------------------
def test_detail_question_matches_a_section_dash_sheet_number():
    """'Detail N on <sheet>' must find the callout when sheets are numbered section-dash-sheet
    (S30-02): the sheet token of the question is compared as written, not forced into another style."""
    index = make_index(callout("S30-02.callout.001", "S30-02", "4", "S30-02"), sheets=("S30-02", "S10-01"))
    a = answer("Where is detail 4 on S30-02 used?", index, llm=None)
    assert a.method == "rule:callouts"
    assert "S30-02" in a.text
    assert a.fact_ids == ["S30-02.callout.001"]


def test_callout_list_is_scoped_to_the_named_sheet():
    """'List the callouts on <sheet>' answers for that sheet, and says so when it has none, instead
    of listing the callouts drawn on other sheets."""
    index = make_index(callout("S10-01.callout.001", "S10-01", "2", "S30-02"), sheets=("S05-04", "S10-01"))
    a = answer("List the callouts on S05-04", index, llm=None)
    assert a.method == "rule:callouts"
    assert "No detail callouts found on S05-04" in a.text

    b = answer("List the callouts on S10-01", index, llm=None)
    assert b.fact_ids == ["S10-01.callout.001"]


def test_how_many_callouts_reference_a_sheet_is_counted():
    """'How many callouts reference <sheet>?' is a count of callouts pointing at that sheet, not a
    missing-sheet question, although it contains the word 'reference'."""
    index = make_index(
        callout("S10-01.callout.001", "S10-01", "1", "S30-02"),
        callout("S10-01.callout.002", "S10-01", "2", "S30-02"),
        callout("S10-01.callout.003", "S10-01", "1", "S30-05"),
        sheets=("S10-01", "S30-02", "S30-05"),
    )
    a = answer("How many callouts reference S30-02?", index, llm=None)
    assert a.method == "rule:callouts"
    assert "2 callout(s) reference S30-02" in a.text
    assert a.fact_ids == ["S10-01.callout.001", "S10-01.callout.002"]


def test_how_many_callouts_reference_a_sheet_of_the_example_set(platform):
    """Five bubbles on the plan and the elevations, and two notes, point at the details sheet."""
    a = answer("How many callouts reference S-301?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert "7 callout(s) reference S-301" in a.text  # five bubbles and two "SEE DETAIL n/S-301" notes
    assert a.sheets == ["S-001", "S-101", "S-201", "S-401"]


def test_callout_question_that_mentions_a_plate_is_not_a_section_question(platform):
    """'How many callouts reference the base plate detail?' is about callouts: the word 'plate'
    must not send it to the member-section rule, which would list every plate label."""
    a = answer("How many callouts reference the base plate detail?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert all(platform.get(fid).kind == "callout" for fid in a.fact_ids)


def test_detail_question_finds_a_reference_written_in_a_note():
    """A detail that is only cited in note text ('SEE DETAIL 6/S502') is still found by 'where is
    detail 6/S502 used', and counted by 'how many callouts reference S502'."""
    index = make_index(
        note_reference("S-210.reference.001", "S-210", "6", "S502", "EMBED PLATE - SEE DETAIL 6/S502"),
        note_reference("S-210.reference.002", "S-210", "B2", "S604", "STIFFENERS - SEE SECT. B2/S604"),
        sheets=("S-210",),
    )
    a = answer("Where is detail 6/S502 used?", index, llm=None)
    assert a.method == "rule:callouts"
    assert a.fact_ids == ["S-210.reference.001"]

    b = answer("Where is section B2/S604 used?", index, llm=None)
    assert b.method == "rule:callouts"
    assert b.fact_ids == ["S-210.reference.002"]

    c = answer("How many callouts reference S502?", index, llm=None)
    assert c.method == "rule:callouts"
    assert c.fact_ids == ["S-210.reference.001"]


def test_detail_question_reports_the_view_itself_not_a_callout_on_its_own_sheet():
    """Once a view-number bubble is read as the view's number, 'where is detail N used' names the
    view; there is no callout fact left to report as 'called out on' its own sheet."""
    index = make_index(
        make_fact(
            "S30-02.view.001",
            "view",
            "PIER CAP AT EXTERIOR STEEL POST",
            "S30-02",
            title="PIER CAP AT EXTERIOR STEEL POST",
            number="4",
            scale="1 : 25",
        ),
        sheets=("S30-02",),
    )
    a = answer("Where is detail 4 on S30-02 used?", index, llm=None)
    assert a.method == "rule:callouts"
    assert "The detail itself: view 4" in a.text
    assert "called out on S30-02" not in a.text
