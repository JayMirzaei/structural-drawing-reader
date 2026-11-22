"""Rules about the set itself: the sheet list, sheets referenced but missing, the views on a sheet,
and which revision counts as the latest."""

from drawing_reader.qa import answer
from drawing_reader.qa.rules.titleblock import _rev_rank
from drawing_reader.schema import SheetMeta
from support import make_fact, make_index


def missing_ref(fid, sheet, target):
    """A note reference to a sheet that is not in the set."""
    text = f"SEE DWG {target}"
    return make_fact(fid, "reference", target, sheet, target_sheet=target, target_in_set=False, context=text)


def set_with_several_gaps():
    """S-101 points at two absent sheets (one of them a lettered variant), S-201 at a third."""
    return make_index(
        missing_ref("S-101.reference.001", "S-101", "S-601"),
        missing_ref("S-101.reference.002", "S-101", "S-701"),
        missing_ref("S-101.reference.003", "S-101", "S-701B"),
        missing_ref("S-201.reference.001", "S-201", "S-901"),
        sheets=("S-101", "S-201"),
    )


# ---- missing sheets -----------------------------------------------------------------------------
def test_missing_sheet_spelled_two_ways_is_reported_once():
    """Two notes naming the same absent sheet with and without a dash describe one gap, not two."""
    index = make_index(
        missing_ref("S-101.reference.001", "S-101", "S-604"),
        missing_ref("S-101.reference.002", "S-101", "S604"),
    )
    a = answer("Which sheets are referenced but not in the set?", index, llm=None)
    assert a.method == "rule:missing"
    assert a.text.startswith("1 referenced sheet(s)")
    assert a.text.count("— referenced on") == 1


def test_missing_sheets_scoped_to_the_sheet_that_references_them():
    """Naming a source sheet reports only that sheet's own gaps, not a gap referenced from elsewhere."""
    a = answer("Which sheets referenced on S-101 are missing?", set_with_several_gaps(), llm=None)
    assert a.method == "rule:missing"
    assert a.text.startswith("3 referenced sheet(s) on S-101")
    assert "S-601" in a.text and "S-701" in a.text and "S-701B" in a.text
    assert "S-901" not in a.text


def test_missing_sheets_scoped_to_a_source_sheet_of_the_example_set(platform):
    """On the example set the framing plan's only gap is the guardrail sheet, cited from its own note."""
    a = answer("Which sheets referenced on S-101 are missing?", platform, llm=None)
    assert a.method == "rule:missing"
    assert a.text.startswith("1 referenced sheet(s) on S-101")
    assert a.fact_ids == ["S-101.reference.002"]


def test_source_sheet_whose_references_are_all_present_says_so(platform):
    """A sheet whose callouts all land inside the set must not be answered with the set's other gaps."""
    a = answer("Which missing sheets are referenced on S-201?", platform, llm=None)
    assert a.method == "rule:missing"
    assert "Every sheet referenced on S-201 is in the set" in a.text
    assert "S-301" in a.text
    assert "501" not in a.text
    on_sheet = sorted(f.id for f in platform.by_kind("reference", "callout") if f.sheet == "S-201")
    assert on_sheet
    assert sorted(a.fact_ids) == on_sheet


def test_named_missing_sheet_reports_only_its_own_references():
    """'Is <absent sheet> referenced anywhere?' answers for that sheet, not for every other gap."""
    a = answer("Is S901 referenced anywhere?", set_with_several_gaps(), llm=None)
    assert a.method == "rule:missing"
    assert "S-901" in a.text and "S-201" in a.text
    for other in ("S-601", "S-701"):
        assert other not in a.text


def test_named_missing_sheet_of_the_example_set(platform):
    """The absent guardrail sheet is found whether or not the question writes the dash."""
    for question in ("Is S501 referenced anywhere?", "Where is S-501 referenced?"):
        a = answer(question, platform, llm=None)
        assert a.method == "rule:missing", question
        assert "501 is referenced but not in this set" in a.text, question
        assert a.sheets == ["S-001", "S-101"], question


def test_named_missing_sheet_with_a_letter_suffix_is_not_its_unlettered_sibling():
    """A lettered sheet (701B) and the plain one (701) are different sheets, even when both are absent."""
    a = answer("Where is S701B referenced?", set_with_several_gaps(), llm=None)
    assert a.method == "rule:missing"
    assert a.fact_ids == ["S-101.reference.003"]
    assert "S-701B is referenced but not in this set" in a.text


def test_unknown_sheet_shaped_word_is_not_answered_by_the_missing_rule(platform):
    """A sheet-like token that is neither in the set nor referenced anywhere yields: the rule must
    not invent a 'not referenced' answer it cannot support."""
    a = answer("Is S99 referenced anywhere?", platform, llm=None)
    assert a.method != "rule:missing"


# ---- sheet list ---------------------------------------------------------------------------------
def test_sheet_question_with_a_topic_filters_by_title():
    """'What sheets have <topic>?' lists the sheets whose title matches, at lower confidence than
    the plain full listing."""
    index = make_index(
        sheets=(
            SheetMeta(page=1, number="S-210", title="GRATING LAYOUT PLANS"),
            SheetMeta(page=2, number="S-001", title="GENERAL NOTES"),
        )
    )
    a = answer("What sheets have grating details?", index, llm=None)
    assert a.method == "rule:sheets"
    assert "S-210" in a.text and "S-001" not in a.text
    assert a.confidence < 0.95

    b = answer("List the sheets and their titles.", index, llm=None)
    assert b.method == "rule:sheets"
    assert "S-210" in b.text and "S-001" in b.text


def test_question_about_one_named_sheet_describes_only_that_sheet():
    """'What is on <sheet>?' has no word 'sheet' in it, yet it asks for that sheet's title and views."""
    index = make_index(
        make_fact("S-001.sheet.001", "sheet", "S-001", "S-001"),
        make_fact("S-001.titleblock.001", "titleblock", "GENERAL NOTES", "S-001", field="sheet_title"),
        make_fact("S-220.sheet.001", "sheet", "S-220", "S-220"),
        make_fact("S-220.titleblock.001", "titleblock", "BRACING ELEVATIONS", "S-220", field="sheet_title"),
        make_fact("S-220.view.001", "view", "NORTH BRACED BAY", "S-220", number="1", title="NORTH BRACED BAY"),
        sheets=(
            SheetMeta(page=1, number="S-001", title="GENERAL NOTES"),
            SheetMeta(page=2, number="S-220", title="BRACING ELEVATIONS", scale="AS NOTED"),
        ),
    )
    a = answer("What is on S-220?", index, llm=None)
    assert a.method == "rule:sheets"
    assert a.confidence == 0.9
    assert "S-220: BRACING ELEVATIONS" in a.text
    assert "NORTH BRACED BAY" in a.text
    assert "S-001" not in a.text
    assert {"S-220.sheet.001", "S-220.titleblock.001", "S-220.view.001"} <= set(a.fact_ids)


def test_named_sheet_questions_owned_by_other_rules_are_left_to_them(platform):
    """Naming a sheet while asking for its scale, its drafter or its views is not a sheet-list
    question, and a sheet number that is not in the set must not produce the full listing."""
    assert answer("What is the scale of S-301?", platform, llm=None).method == "rule:scale"
    assert answer("Who drew S-301?", platform, llm=None).method == "rule:project"
    assert answer("List the views on S-201?", platform, llm=None).method == "rule:views"
    unknown = answer("What is sheet S-901 about?", platform, llm=None)
    assert unknown.method != "rule:sheets" or not unknown.text.startswith("The set has")


def test_named_sheet_and_full_listing_on_the_example_set(platform):
    """Naming one sheet answers for that sheet alone; 'list the sheets' still lists all five."""
    a = answer("What is the title of S-201?", platform, llm=None)
    assert a.method == "rule:sheets"
    assert a.confidence == 0.9
    assert "FRAME ELEVATIONS" in a.text
    assert "- S-001:" not in a.text

    b = answer("List the sheets and their titles.", platform, llm=None)
    assert b.method == "rule:sheets"
    assert b.confidence == 0.95
    assert b.text.startswith("The set has 5 sheet(s):")


# ---- views --------------------------------------------------------------------------------------
def test_views_of_a_named_sheet_are_all_listed_and_nothing_else(platform):
    """'List the views on <sheet>' returns every view title of that sheet, whatever words the titles
    contain, and no view of another sheet."""
    a = answer("List the views on S-301", platform, llm=None)
    assert a.method == "rule:views"
    assert a.sheets == ["S-301"]
    for title in ("COLUMN BASE PLATE", "BEAM TO COLUMN SHEAR TAB", "BRACE GUSSET AT COLUMN BASE"):
        assert title in a.text
    for other in ("ELEVATION ON GRID", "FRAMING PLAN", "ISOMETRIC VIEW"):
        assert other not in a.text

    b = answer("Which views are on S-201?", platform, llm=None)
    assert b.method == "rule:views"
    assert b.sheets == ["S-201"]
    assert "ELEVATION ON GRID C" in b.text and "ELEVATION ON GRID 1" in b.text
    assert b.text.count("- view") == 2


def test_views_rule_on_a_sheet_without_views_and_on_an_unknown_sheet():
    """A sheet with no view titles says so; a sheet number outside the set yields instead of listing
    every view of the document."""
    index = make_index(
        make_fact("S-220.view.001", "view", "NORTH BRACED BAY", "S-220", number="1", title="NORTH BRACED BAY"),
        sheets=("S-001", "S-220"),
    )
    a = answer("List the views on S-001", index, llm=None)
    assert a.method == "rule:views"
    assert "No view titles found on S-001" in a.text

    b = answer("List the views on S-909", index, llm=None)
    assert b.method != "rule:views"


# ---- revisions ----------------------------------------------------------------------------------
def test_numeric_revision_outranks_a_lettered_design_stage():
    """Lettered revisions are pre-issue stages, numbered ones come after issue: a number is always
    the later one, although a letter sorts higher as plain text."""
    numbered = make_fact("S-101.revision.001", "revision", "", "S-101", number="3")
    lettered = make_fact("S-101.revision.002", "revision", "", "S-101", number="F")
    assert max([lettered, numbered], key=_rev_rank) is numbered
    assert max([numbered, lettered], key=_rev_rank) is numbered
