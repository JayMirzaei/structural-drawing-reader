"""The dimensions rule: which dimension strings answer a height, width or size question, how a
named sheet or view narrows them, and which questions it must leave to other rules."""

from drawing_reader.qa import answer
from drawing_reader.qa.rules.geometry import rule_dimensions
from drawing_reader.qa.text import tokens
from drawing_reader.schema import Fact
from support import make_index


def dimension(fid, value, sheet, view, orientation="horizontal"):
    """A dimension string in millimetres that belongs to a titled view."""
    return Fact(
        id=fid,
        kind="dimension",
        value=value,
        unit="mm",
        sheet=sheet,
        page=1,
        view=view,
        bbox=(10, 10, 60, 20),
        source_text=value,
        attrs={"orientation": orientation},
    )


def test_height_and_width_questions_are_answered_from_dimension_strings(platform):
    """A height question lists the vertical dimension strings and a width question the horizontal
    ones; the answer cites dimension facts only."""
    a = answer("Tier heights?", platform, llm=None)
    assert a.method == "rule:dimensions"
    assert "3600" in a.text and "1100" in a.text
    assert "6000" not in a.text
    assert "S-201" in a.sheets
    assert a.fact_ids and all(platform.get(fid).kind == "dimension" for fid in a.fact_ids)

    b = answer("What is the bay width?", platform, llm=None)
    assert b.method == "rule:dimensions"
    assert "6000" in b.text and "4500" in b.text
    assert "3600" not in b.text


def test_dimensions_are_scoped_to_the_named_sheet():
    """Naming a sheet restricts the listed dimensions to that sheet."""
    index = make_index(
        dimension("S-110.dimension.001", "2400", "S-110", "PLAN"),
        dimension("S-210.dimension.001", "7300", "S-210", "ELEVATION"),
        sheets=("S-110", "S-210"),
    )
    a = answer("What is the width on S-210?", index, llm=None)
    assert a.method == "rule:dimensions"
    assert "7300" in a.text and "2400" not in a.text


def test_dimensions_rule_yields_without_dimension_facts():
    """An index with no dimension strings gets no empty 'dimensions' answer from this rule."""
    empty = make_index(sheets=("S-110",))
    assert rule_dimensions("dimensions?", tokens("dimensions?"), empty) is None


def test_level_question_stays_with_the_elevation_rule(platform):
    """Asking for the elevation of a named level is answered from the level markers."""
    a = answer("What is the elevation of T.O. STEEL?", platform, llm=None)
    assert a.method == "rule:elevations"
    assert "T.O. STEEL: 3600 mm" in a.text


def test_thickness_question_is_not_a_dimension_string_question(platform, idx):
    """A plate thickness is stated in note text ('38mm THICK'), not by a dimension string: it goes
    to the component rule when such a note exists, and never to the dimensions rule."""
    a = answer("Base plate thickness?", idx, llm=None)
    assert a.method == "rule:component-spec"
    assert "38mm" in a.text

    b = answer("Base plate thickness?", platform, llm=None)
    assert b.method != "rule:dimensions"


def test_base_plate_size_is_read_from_the_base_plate_view(platform):
    """'Base plate size' means the plan dimensions drawn in the base plate detail, not the plate
    thickness labels and not the dimensions of another view."""
    for question in ("What is the base plate size?", "Base plate plan dimensions?"):
        a = answer(question, platform, llm=None)
        assert a.method == "rule:dimensions", question
        assert "350" in a.text and "250" in a.text, question
        assert a.sheets == ["S-301"], question
        assert all(platform.get(fid).view == "COLUMN BASE PLATE" for fid in a.fact_ids), question


def test_member_size_questions_still_go_to_the_section_rule(platform):
    """A size question about a member is a designation lookup, untouched by the dimensions rule."""
    for question in ("Column size?", "What are the member sizes?", "What are the column sections?"):
        a = answer(question, platform, llm=None)
        assert a.method == "rule:sections", question
        assert "HSS152X152X9.5" in a.text, question


def test_view_scoping_keeps_the_view_matching_most_question_words():
    """A question naming two words ('base plate') prefers the view whose title has both over a
    view sharing only one of them."""
    index = make_index(
        dimension("S-301.dimension.001", "380", "S-301", "BASE PLATE DETAIL"),
        dimension("S-301.dimension.002", "460", "S-301", "BASE PLATE DETAIL", "vertical"),
        dimension("S-301.dimension.003", "715", "S-301", "CAP PLATE AT UPPER LEVEL", "diagonal"),
        sheets=("S-301",),
    )
    a = answer("What is the base plate size?", index, llm=None)
    assert a.method == "rule:dimensions"
    assert "380" in a.text and "460" in a.text and "715" not in a.text
    assert a.fact_ids == ["S-301.dimension.001", "S-301.dimension.002"]
