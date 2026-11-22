"""Material notes: how a 'COMPONENT: size SPEC, Fy' clause is parsed, and how the materials rule
picks the component a question asks about."""

from drawing_reader.parse.sheet.parser import SheetParser
from drawing_reader.qa import answer
from drawing_reader.qa.rules.materials import rule_materials
from drawing_reader.qa.text import tokens
from support import make_fact, make_index, make_sheet


def parse_material_clause(body):
    """The material facts the parser makes from one general-notes clause."""
    parser = SheetParser(make_sheet([]))
    note = parser._add("note", body, (0, 0, 10, 10), body)
    parser._parse_material(note, body, heading=None)
    return [f for f in parser.facts if f.kind == "material"]


def material(fid, component, spec, sheet="S-001"):
    return make_fact(fid, "material", f"{component.upper()}: {spec}", sheet, component=component, spec=spec)


def frame_materials():
    """A notes sheet where plate steel is specified under 'Connections', with no 'Plates' line."""
    return make_index(
        material("S-001.material.001", "Columns", "ASTM A992"),
        material("S-001.material.002", "Beams", "ASTM A992"),
        material("S-001.material.003", "Braces", "ASTM A500"),
        material("S-001.material.004", "Connections", "CSA G40.21"),
        sheets=("S-001",),
    )


# ---- parsing ------------------------------------------------------------------------------------
def test_clause_citing_several_standards_gives_one_fact_per_standard():
    """A lettered sub-list of standards in one clause must not collapse to a single fact: a coating
    standard cited last would hide the design standard cited first."""
    body = (
        "STEEL WORK SHALL CONFORM TO: "
        'a. CSA S16 "DESIGN OF STEEL STRUCTURES" '
        'b. CSA W59 "WELDED STEEL CONSTRUCTION" '
        'c. ASTM A123 / A123M "ZINC COATINGS ON STEEL PRODUCTS"'
    )
    assert {f.attrs["spec"] for f in parse_material_clause(body)} == {"CSA S16", "CSA W59", "ASTM A123 / A123M"}


def test_size_written_before_the_standard_is_kept_and_never_taken_from_its_digits():
    """'COMPONENT: size STANDARD' puts the size ahead of the citation; a clause with no size must
    not borrow one from the digits of the standard's own number."""
    (metric,) = parse_material_clause("ANCHOR RODS: M24 ASTM F1554 UNO")
    assert metric.attrs["size"] == "M24"
    (imperial,) = parse_material_clause('STUD DIA.: 2" ASTM A108 UNO')
    assert imperial.attrs["size"] == '2"'
    (no_size,) = parse_material_clause("BEAMS: ASTM A992 Fy=345 MPa")
    assert no_size.attrs["size"] == ""


def test_size_of_the_example_set_bolts(platform):
    """The bolt clause of the example set carries its size; the beam clause carries none."""
    by_component = {m.attrs["component"]: m.attrs for m in platform.by_kind("material")}
    assert by_component["Bolts"]["size"] == "M20"
    assert by_component["Beams"]["size"] == ""


def test_upper_yield_limit_is_kept_apart_from_the_nominal_yield():
    """A clause stating both Fy and a capped Fymax records both values, each in its own field."""
    (brace,) = parse_material_clause("BRACES: ASTM A500 Fy= 317 MPa, Fymax= 450 MPa")
    assert brace.attrs["fy_mpa"] == "317"
    assert brace.attrs["fy_max_mpa"] == "450"


# ---- answering ----------------------------------------------------------------------------------
def test_bolt_size_question_is_answered_from_the_material_note(platform):
    """'Bolt size' is a materials question when the bolt clause states a size."""
    for question in ("What is the bolt size?", "Bolt size and grade?"):
        a = answer(question, platform, llm=None)
        assert a.method == "rule:materials", question
        assert "M20" in a.text and "A325M" in a.text, question
        assert a.fact_ids == ["S-001.material.005"], question


def test_size_question_about_a_plate_is_not_a_materials_question(platform):
    """'Base plate size' asks for dimensions: no material clause carries a size for it."""
    assert answer("What is the base plate size?", platform, llm=None).method != "rule:materials"


def test_bolt_grade_question(platform):
    """A grade question naming a component returns that component's standard."""
    a = answer("What is the bolt grade?", platform, llm=None)
    assert a.method == "rule:materials"
    assert "A325M" in a.text
    assert "F1554" not in a.text


def test_compound_component_with_an_unknown_word_is_declined(platform):
    """'Anchor washer': 'anchor' hits the anchor-rod clause but no clause mentions washers, so
    answering with the anchor rod grade would be confidently wrong."""
    question = "what grade is the anchor washer?"
    assert rule_materials(question, tokens(question), platform) is None
    assert answer("What grade is the anchor washer?", platform, llm=None).method != "rule:materials"


def test_materials_question_is_scoped_to_the_named_sheet():
    """Naming a sheet returns only that sheet's material facts, and the rule yields when the sheet
    has none rather than answer with another sheet's."""
    index = make_index(
        material("S-001.material.001", "Bolts", "ASTM F3125"),
        material("S-310.material.001", "Grating", "ASTM A1011", sheet="S-310"),
        sheets=("S-001", "S-310", "S-320"),
    )
    a = answer("What materials are specified for S-310?", index, llm=None)
    assert a.method == "rule:materials"
    assert "ASTM A1011" in a.text and "ASTM F3125" not in a.text

    b = answer("What materials are specified for S-320?", index, llm=None)
    assert b.method != "rule:materials"


def test_plates_resolve_to_the_connections_clause_in_a_list_of_components():
    """Plate steel is often specified under 'CONNECTIONS': a question listing columns, beams, braces
    and plates must return all four clauses, not only the three named literally."""
    a = answer("Steel grades for columns / beams / braces / plates?", frame_materials(), llm=None)
    assert a.method == "rule:materials"
    assert a.confidence == 0.9
    assert a.fact_ids == ["S-001.material.001", "S-001.material.002", "S-001.material.003", "S-001.material.004"]
    assert "CSA G40.21" in a.text


def test_plates_alone_resolve_to_the_connections_clause_only():
    """With no 'Plates' clause, a plates question returns the 'Connections' clause and nothing else."""
    a = answer("What is the steel grade of the plates?", frame_materials(), llm=None)
    assert a.method == "rule:materials"
    assert a.confidence == 0.9
    assert a.fact_ids == ["S-001.material.004"]


def test_exact_component_match_beats_the_synonym():
    """When the notes do have a 'Plates' clause, the 'Connections' clause is not pulled in as well."""
    index = make_index(
        material("S-001.material.001", "Plates", "CSA G40.21"),
        material("S-001.material.002", "Connections", "ASTM A325M"),
        sheets=("S-001",),
    )
    a = answer("What is the steel grade of the plates?", index, llm=None)
    assert a.method == "rule:materials"
    assert a.fact_ids == ["S-001.material.001"]
