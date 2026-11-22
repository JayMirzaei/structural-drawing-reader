"""Answer rules on small hand-built indexes: when each rule answers, what it says, and when it
must decline so a better rule (or the provider) gets the question."""

from __future__ import annotations

import pytest

from drawing_reader.parse import SheetParser
from drawing_reader.qa import MIN_CONFIDENCE, answer, answer_by_rules, tokens
from drawing_reader.qa.rules.loads import RE_PARAM
from drawing_reader.qa.rules.materials import rule_component_spec
from drawing_reader.qa.rules.titleblock import _scale_note
from drawing_reader.qa.text import word_match
from drawing_reader.schema import Fact, SheetMeta
from support import make_index, make_run, make_sheet


def _fact(kind, value, sheet="S-101", n=1, view=None, source=None, **attrs):
    return Fact(
        id=f"{sheet}.{kind}.{n:03d}",
        kind=kind,
        value=value,
        sheet=sheet,
        page=1,
        view=view,
        bbox=(10, 10 * n, 90, 10 * n + 8),
        source_text=source or value,
        confidence=0.85,
        attrs=attrs,
    )


def _notes(*texts, heading=None):
    """An index of one sheet whose notes carry the given texts (all under one heading, if given)."""
    attrs = {"heading": heading} if heading else {}
    return make_index(*[_fact("note", t[:20], n=i, source=t, **attrs) for i, t in enumerate(texts, 1)])


def _label(n, section, family="W", orientation="vertical", view=None, sheet="S-101"):
    return _fact("label", section, sheet=sheet, n=n, view=view, section=section, family=family, orientation=orientation)


def _by_method(question, idx):
    return {a.method: a for a in answer_by_rules(question, idx)}


# --- design criteria: 'NAME = value unit' ---------------------------------------------------------


def test_parameter_unit_is_matched_in_any_letter_case():
    """A unit glued to the value in odd capitals ("2.48KPa") is still the unit, and the value is whole."""
    m = RE_PARAM.search("Ss = 2.48KPa")
    assert (m["val"], m["unit"]) == ("2.48", "KPa")


def test_parameter_value_is_never_cut_short():
    """A value followed directly by another symbol keeps all its digits."""
    assert RE_PARAM.search("Tf = 0.4Tf = 160kN")["val"] == "0.4"
    assert RE_PARAM.search("Sa(0.5) = 0.23")["val"] == "0.23"


def test_first_letter_of_a_word_is_not_a_unit():
    """The "m" of "meters" is not the unit "m"."""
    assert RE_PARAM.search("Ss = 1.7 meters")["unit"] is None


def test_fraction_after_equals_is_not_a_parameter():
    """A thickness written as an imperial fraction ('t = 3/32"') is not a design value "3"."""
    assert RE_PARAM.search('TIES TO BE "HEAVY DUTY" CORRUGATED - t = 3/32" @ 16" O/C') is None


def test_snow_load_answer_gives_the_number_and_unit():
    """A snow parameter under a snow heading answers the snow load question with value and unit."""
    a = answer("What is the snow load?", _notes("Ss = 2.48KPa", heading="3. Snow Load"), llm=None)
    assert a.method == "rule:loads"
    assert "2.48 KPa" in a.text


def test_period_qualifier_and_enumerated_site_field_are_parameters():
    """A spectral value with a numeric period ("Sa(0.5)= ...") and a "SITE CLASS: C" field both answer."""
    idx = _notes("Sa(0.5)= 0.23", "SITE CLASS: C")
    spectral = answer("What is Sa?", idx, llm=None)
    assert spectral.method == "rule:loads" and "Sa(0.5) = 0.23" in spectral.text
    site = answer("What is the site class?", idx, llm=None)
    assert site.method == "rule:loads" and "SITE CLASS = C" in site.text


def test_question_naming_two_symbols_gets_both():
    """ "What are Rd and Ro" answers with both symbols, not only the first one named."""
    a = answer("What are Rd and Ro?", _notes("SEISMIC: Rd = 2.0 Ro = 1.5"), llm=None)
    assert "Rd = 2.0" in a.text and "Ro = 1.5" in a.text


def test_topic_word_before_a_list_covers_every_clause_in_it():
    """The topic word in front of an unbroken list ("SEISMIC: Rd = .. Ro = ..") applies to all of it."""
    a = answer("What are the seismic parameters?", _notes("SEISMIC: Rd = 2.0 Ro = 1.5"), llm=None)
    assert "Rd = 2.0" in a.text and "Ro = 1.5" in a.text


def test_clause_with_its_own_topic_word_does_not_inherit_the_first_one():
    """In "SNOW LOAD: Ss = .. WIND: q = .." the wind value is not part of the snow load answer."""
    a = answer("What is the snow load?", _notes("SNOW LOAD: Ss = 1.9 WIND: q = 0.52"), llm=None)
    assert "Ss = 1.9" in a.text and "q = 0.52" not in a.text


def test_qualifier_in_the_question_narrows_the_rows():
    """Asking for one period of a spectral table returns that period only."""
    idx = _notes("Sa(0.5)= 0.23 Sa(1.0)= 0.12 Sa(2.0)= 0.055", "SITE CLASS: C")
    a = answer("What is the site class and Sa(0.5)?", idx, llm=None)
    assert "SITE CLASS = C" in a.text and "Sa(0.5) = 0.23" in a.text
    assert "Sa(1.0)" not in a.text


def test_weak_strength_topic_needs_the_subject_named_in_the_question():
    """Concrete f'c rows answer a concrete strength question, not one about another material."""
    idx = _notes("f'c = 35 MPa", heading="CAST-IN-PLACE CONCRETE")
    assert "rule:loads" in _by_method("what is the concrete strength?", idx)
    assert "rule:loads" not in _by_method("what is the minimum compressive strength of masonry mortar?", idx)


def test_criteria_label_and_value_in_separate_runs_are_paired():
    """A design-criteria table states a label and its value as two runs on one row; labels other
    than "<word> LOAD" (a pressure, a factor) are paired too, and a heading is not a label."""
    runs = [
        make_run("HOURLY WIND PRESSURE (q 1/10)", 60, 150, 9, x1=260),
        make_run("0.38 kPa", 320, 150, 9, x1=362),
        make_run("SLS IMPORTANCE FACTOR", 60, 185, 9, x1=215),
        make_run("0.9 (LOW IMPORTANCE)", 320, 185, 9, x1=430),
        make_run("GENERAL NOTES", 60, 220, 9, x1=150),
        make_run("0.38 kPa", 320, 220, 9, x1=362),
    ]
    parser = SheetParser(make_sheet(runs))
    parser.parse_load_table()
    pairs = {
        f.attrs["param_name"]: (f.attrs["param_value"], f.attrs["param_unit"])
        for f in parser.facts
        if f.attrs.get("param_name")
    }
    assert pairs == {"HOURLY WIND PRESSURE (q 1/10)": ("0.38", "kPa"), "SLS IMPORTANCE FACTOR": ("0.9", "")}


# --- sheets referenced but missing ----------------------------------------------------------------


def _note_references(*lines):
    runs = [make_run(text, 60, 120 + 30 * i, 8, x1=460) for i, text in enumerate(lines)]
    parser = SheetParser(make_sheet(runs))
    parser.parse_notes()
    return [f for f in parser.facts if f.kind == "reference"]


def test_a_drawing_series_is_not_a_sheet_reference():
    """ "REFER TO DRAWINGS S300 SERIES" names a group of sheets, not a sheet numbered 300; a plain
    "SEE S40" is a reference."""
    refs = _note_references("1. REFER TO DRAWINGS S300 SERIES FOR TYPICAL DETAILS & SCHEDULES.", "2. SEE S40, TYP.")
    targets = {f.attrs["target_sheet"] for f in refs}
    assert len(targets) == 1
    assert not any("300" in t for t in targets)
    assert "40" in next(iter(targets))


def test_the_adjective_reference_does_not_ask_for_missing_sheets():
    """ "Reference wind pressure" is code wording; only a question about referenced sheets is
    answered by the missing-sheets rule."""
    idx = _notes("REFER TO DRAWINGS S300 SERIES FOR TYPICAL DETAILS")
    idx.facts.append(_fact("reference", "S-88", target_sheet="S-88", target_in_set=False))
    assert "rule:missing" not in _by_method("what is the reference wind pressure q 1/50?", idx)
    cands = answer_by_rules("which sheets are referenced but not in the set?", idx)
    assert cands and cands[0].method == "rule:missing"


# --- member sizes ---------------------------------------------------------------------------------


def test_member_word_inside_a_hyphenated_word_is_not_a_member_question():
    """ "Post-tensioning" is not a question about posts; "post sizes" is."""
    idx = make_index(_label(1, "W250x58"))
    assert "rule:sections" not in _by_method("what are the post-tensioning requirements?", idx)
    assert "rule:sections" in _by_method("what are the post sizes?", idx)


def test_sections_differing_only_in_the_case_of_x_are_one_group():
    """ "W200X46" and "W200x46" are the same section: listed once, in the first spelling, counted twice."""
    idx = make_index(_label(1, "W200X46"), _label(2, "W200x46"))
    a = answer("what are the column sizes?", idx, llm=None)
    assert a.text.count("W200") == 1
    assert "W200X46" in a.text and "S-101×2" in a.text


def test_member_question_falls_back_to_any_orientation_with_a_caveat():
    """A brace labelled on a leader reads horizontal; with no diagonal label the rule answers from
    every orientation, at lower confidence, and says so."""
    idx = make_index(_label(1, "HSS102x102x6.4", "HSS", "horizontal"), _label(2, "W200x46"))
    a = _by_method("what is the brace member size on S-101?", idx)["rule:sections"]
    assert "HSS102x102x6.4" in a.text
    assert a.confidence == 0.75
    assert any("regardless of orientation" in c for c in a.caveats)


def test_concrete_and_locator_questions_about_members_are_not_confident_size_answers():
    """A concrete strength question that mentions columns, or "which sheet shows ...", is not a
    confident member-size answer."""
    idx = make_index(_label(1, "HSS102x102x6.4", "HSS", "horizontal"), _label(2, "W200x46"))
    concrete = _by_method("what is the concrete strength for the columns?", idx).get("rule:sections")
    assert concrete is None or concrete.confidence <= 0.5
    assert _by_method("which sheet shows the column splice?", idx)["rule:sections"].confidence <= 0.6


def test_view_named_in_the_question_scopes_the_member_answer():
    """Naming a frame view limits a beam question to the labels inside that view."""
    idx = make_index(
        _fact("view", "BENT 3 (C-D)", n=1, title="BENT 3 (C-D)", scale="1 : 50"),
        _label(1, "W410x54", orientation="horizontal", view="BENT 1 (C-D)"),
        _label(2, "W530x92", orientation="horizontal", view="BENT 3 (C-D)"),
    )
    a = _by_method("what beam size is at the top of bent 3 (c-d)?", idx)["rule:sections"]
    assert "W530x92" in a.text and "W410x54" not in a.text
    # no column is labelled in that view: the rule does not answer "none" for the scoped question
    assert "rule:sections" not in _by_method("what column size is in bent 3 (c-d)?", idx)


def test_member_size_stated_in_a_note_comes_before_labels():
    """A note that states the size of the member asked about beats the labels found by orientation."""
    sentence = "STAIR STRINGERS TO BE FABRICATED FROM C250x23 CHANNELS, U.N.O. ON DRAWINGS."
    idx = make_index(
        _label(1, "W360x45", orientation="diagonal"),
        _label(2, "C250x23", "C", "diagonal"),
        _label(3, "W310x39", orientation="diagonal"),
        _fact("note", sentence),
    )
    a = _by_method("what size are the stair stringers?", idx)["rule:sections"]
    assert "C250x23" in a.text and "W360x45" not in a.text


# --- materials, grout, component specs ------------------------------------------------------------


def test_yield_strength_question_is_answered_from_the_material_clause():
    """The yield strength of a named component comes from its material fact."""
    idx = make_index(
        _fact(
            "material",
            "CSA G40.21",
            source="ANGLES: CSA G40.21 300W",
            component="Angles",
            spec="CSA G40.21",
            fy_mpa=300,
        )
    )
    a = answer("What is the yield strength of the angles?", idx, llm=None)
    assert a.method == "rule:materials" and "300" in a.text


def test_repeated_material_rows_are_listed_once_with_all_their_sheets():
    """The same material clause on several sheets is one row that names every sheet and the count."""

    def bar(n, sheet):
        return _fact(
            "material",
            "12.7 x 90 ASTM A572 FLAT BAR",
            sheet=sheet,
            n=n,
            component="",
            spec="ASTM A572",
            fy_mpa="",
            fy_max_mpa="",
            size="",
        )

    idx = make_index(bar(1, "S-101"), bar(2, "S-102"), bar(3, "S-102"), sheets=("S-101", "S-102"))
    a = answer("What materials are specified?", idx, llm=None)
    assert a.method == "rule:materials"
    assert a.text.count("ASTM A572") == 1
    assert "S-101, S-102 (×3)" in a.text


def test_materials_are_listed_only_for_a_generic_materials_question():
    """ "What materials are specified?" lists everything; a question about one product does not."""
    idx = make_index(
        _fact("material", "ASTM A325M", n=1, component="Bolts", spec="ASTM A325M"),
        _fact("material", "CSA G40.21", n=2, component="Plates", spec="CSA G40.21"),
    )
    assert "rule:materials" in _by_method("what materials are specified?", idx)
    assert "rule:materials" not in _by_method("what is the timber joist size and grade?", idx)


def test_grout_rule_answers_thickness_only():
    """The grout rule reads a thickness; a strength question is left to other rules."""
    idx = make_index(_fact("note", "40mm NON-SHRINK GROUT, TYP"))
    assert "rule:grout" in _by_method("what is the grout thickness?", idx)
    assert "rule:grout" not in _by_method("what grout strength is required under the equipment pads?", idx)


def test_component_spec_counts_the_words_of_the_sheet_title():
    """A note that says only "16mm Plate" answers a gusset plate question when the sheet's title
    supplies the other words; without the title too little of the question is covered."""
    question = "what is the gusset plate thickness at the wind brace connections?"
    titled = SheetMeta(page=1, number="S-401", title="WIND BRACE CONNECTION: GUSSET PLATE DETAIL")
    idx = make_index(_fact("note", "16mm Plate", sheet="S-401"), sheets=(titled,))
    found = rule_component_spec(question, tokens(question), idx)
    assert found is not None and "16mm Plate" in found.text
    idx.sheets[0].title = ""
    assert rule_component_spec(question, tokens(question), idx) is None


def test_weld_answer_adds_the_size_written_in_a_note_for_the_named_connection():
    """A weld size tabulated in text ("K2 = 9.5mm") is added to the weld symbols for a question
    about that connection, and other connections' rows are left out."""
    idx = make_index(
        _fact("weld", "6", sheet="S-401", n=1, sides="both", typical=False),
        _fact("note", "STIFFENER PLATE & WELD:", sheet="S-401", n=20),
        _fact("text", "K2 = 9.5mm", sheet="S-401", n=21),
        _fact("text", "K7 = 5mm", sheet="S-401", n=40),
        sheets=("S-401",),
    )
    a = _by_method("what weld size is used at connection k2?", idx)["rule:weld"]
    assert "6 mm fillet" in a.text
    assert "K2 = 9.5mm" in a.text and "K7" not in a.text


# --- elevations and dimensions --------------------------------------------------------------------


def test_elevation_rule_matches_level_names_as_whole_words():
    """An elevation question about a named level is answered; a question that only mentions the
    level, or a mark that merely contains a short level name, is not."""
    idx = make_index(_fact("elevation", "7200", n=1, name="Level 3"), _fact("elevation", "0", n=2, name="CP"))
    assert "rule:elevations" in _by_method("what is the elevation of level 3?", idx)
    assert "rule:elevations" not in _by_method("what floor grating and thickness is used on level 3?", idx)
    assert "rule:elevations" not in _by_method("what anchor rods are specified for cap plate CP-C?", idx)


def test_dimension_rule_declines_when_the_subject_matches_no_view():
    """A question about a thing that is not a dimension subject gets no list of every dimension."""
    idx = make_index(
        _fact("dimension", "31000", n=1, view="PLATFORM PLAN", orientation="horizontal"),
        _fact("dimension", "4500", n=2, view="PLATFORM PLAN", orientation="horizontal"),
    )
    assert "rule:dimensions" not in _by_method("what is the monorail capacity and monorail span?", idx)
    assert "rule:dimensions" in _by_method("what is the bay width?", idx)


def test_dimension_negative_on_an_orientation_cue_alone_is_not_confident():
    """ "How high ... on S-101" with no vertical dimension on that sheet is a weak "none found"."""
    idx = make_index(_fact("dimension", "750", sheet="S-102", orientation="vertical"), sheets=("S-101", "S-102"))
    assert _by_method("how high is the bay on S-101?", idx)["rule:dimensions"].confidence <= 0.5


def test_elevation_question_is_not_answered_with_dimensions():
    """ "What is the elevation of ..." is not a request for vertical dimensions."""
    idx = make_index(_fact("dimension", "41250", view="ROOF PLAN", orientation="vertical"))
    assert "rule:dimensions" not in _by_method("what is the elevation of the upper roof metal deck?", idx)
    assert "rule:dimensions" in _by_method("what are the vertical dimensions?", idx)


# --- scale ----------------------------------------------------------------------------------------


def test_view_named_in_the_question_scopes_the_scale_answer():
    """ "Scale of view FR-02" answers with that view's scale, not every view's."""
    idx = make_index(
        _fact("view", "FR-01", n=1, title="FR-01", scale="1 : 10"),
        _fact("view", "FR-02", n=2, title="FR-02", scale="1 : 25"),
    )
    a = _by_method("what is the scale of view fr-02?", idx)["rule:scale"]
    assert "FR-02" in a.text and "1 : 25" in a.text
    assert "FR-01" not in a.text


def _measured_view(n, titled, measured, **attrs):
    return _fact(
        "view", f"V{n}", n=n, title=f"V{n}", scale=titled, scale_measured=measured, scale_support="6/9", **attrs
    )


def test_print_reduction_explains_a_measured_scale_that_differs_from_the_titled_one():
    """On a reduced print every view measures smaller by one factor; that is noted, not warned about."""
    assert "print reduction" in _scale_note(_measured_view(1, "1 : 20", "1 : 50", print_reduction=2.5))


def test_scale_mismatch_without_a_sheet_wide_factor_still_warns():
    """With no reduction factor for the sheet, a measured scale unlike the titled one is a warning."""
    assert "check:" in _scale_note(_measured_view(2, "1 : 20", "1 : 50"))


def test_view_that_disagrees_with_the_sheet_reduction_factor_still_warns():
    """A view whose measured scale does not fit the sheet's own reduction factor keeps its warning."""
    assert "check:" in _scale_note(_measured_view(3, "1 : 20", "1 : 100", print_reduction=2.5))


# --- project, location, sheets by discipline ------------------------------------------------------


def test_question_about_an_absent_project_field_does_not_list_the_other_fields():
    """ "Who is the client?" on a set with only a project number must not answer with that number,
    and stays below the confidence at which an answer is shown."""
    idx = make_index(_fact("titleblock", "70314455", field="Project Number"), project={"Project Number": "70314455"})
    a = _by_method("who is the client?", idx)["rule:project"]
    assert "70314455" not in a.text
    assert a.confidence < MIN_CONFIDENCE
    assert "70314455" in _by_method("what is the project number?", idx)["rule:project"].text


def test_location_answer_names_other_places_and_asks_for_a_check():
    """The location answer gives the address found on most sheets, lists other addresses read, and
    says to check it (a consultant's own address can sit in the same title block)."""

    def place(n, value, sheet):
        return _fact("titleblock", value, sheet=sheet, n=n, field="Location", loc_kind="address")

    site = "4718 ORCHARD RD, LARKSPUR FALLS, MB"
    idx = make_index(
        place(1, site, "S-101"),
        place(2, site, "S-102"),
        place(3, "92 FOUNDRY LANE", "S-101"),
        sheets=("S-101", "S-102"),
        project={"Location": site},
    )
    a = answer("Where is the project?", idx)
    assert a.method == "rule:location"
    assert "4718 ORCHARD RD" in a.text and "92 FOUNDRY LANE" in a.text
    assert "check it" in a.text


def test_discipline_question_lists_sheets_by_number_prefix():
    """ "Which sheets are structural?" lists the S sheets of a multi-discipline set."""
    idx = make_index(sheets=("A02-01", "S02-01", "S30-01", "M20-01"))
    a = _by_method("which sheets are structural?", idx)["rule:sheets"]
    assert "S02-01" in a.text and "S30-01" in a.text and "A02-01" not in a.text
    assert a.confidence >= 0.85
    assert "A02-01" in _by_method("list the architectural sheets", idx)["rule:sheets"].text


def test_discipline_question_declines_when_prefixes_do_not_name_a_discipline():
    """A set numbered with a letter that is no discipline code gives no "structural sheets" list."""
    idx = make_index(sheets=("D.1.4.2", "D.1.4.3"))
    a = _by_method("which sheets are structural?", idx).get("rule:sheets")
    assert a is None or "D.1.4.2" not in a.text


# --- text search and question words ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "words", "matches"),
    [
        ("dia", {"diaphragm", "chords"}, False),
        ("dia", {"450", "dia."}, True),
        ("dia", {"dia"}, True),
        ("piles", {"timber", "pile"}, True),
        ("welds", {"weld"}, True),
    ],
)
def test_short_search_tokens_match_whole_words_and_plurals(token, words, matches):
    """A three-letter token matches the word itself (with its full stop), not a longer word that
    starts with it; a plural matches its singular."""
    assert word_match(token, words) is matches


def test_rare_word_carries_the_text_search_confidence():
    """A word found in one fact decides the answer; a word that is in nearly every fact must not
    drag the confidence down."""
    pile = "450 CONCRETE PILE C/W 6-25M VERT"
    idx = make_index(_fact("note", pile, n=1), *[_fact("note", "FOOTING SCHEDULE NOTE", n=n) for n in range(2, 12)])
    a = _by_method("are there any piles in the footing?", idx)["rule:text-search"]
    assert "PILE" in a.text
    assert a.confidence >= 0.55


def test_who_to_contact_keeps_its_keywords():
    """ "Who do I contact ..." is a keyword question: its content words survive the stop-word filter."""
    assert tokens("who do i contact to resolve a discrepancy?") == ["contact", "resolve", "discrepancy"]


def test_a_question_made_only_of_filler_words_has_no_keywords():
    """ "Which drawings are there?" has no keyword left to search for."""
    assert tokens("which drawings are there?") == []
