"""Design-load questions: values written as 'NAME = value' in the notes, and the explicit answer
when a set states no forces or loads at all."""

from __future__ import annotations

from drawing_reader.qa import THRESHOLD, answer
from drawing_reader.schema import Index, SheetMeta
from support import make_fact, make_index


def criteria_index() -> Index:
    """Two design-criteria notes, each a list of 'NAME = value' clauses under its own heading."""
    return make_index(
        make_fact("S-001.note.001", "note", "a. Ss = 1.9 kPa b. Sr = 0.2 kPa", "S-001", heading="Snow Loads"),
        make_fact("S-001.note.002", "note", "Rd = 3.0 Ro = 1.6", "S-001", heading="Seismic Design Data"),
        sheets=["S-001"],
    )


def test_a_named_symbol_returns_only_that_value():
    """Asking for one symbol by name gives that value, not its neighbour in the same clause list."""
    a = answer("What is Rd?", criteria_index(), llm=None)
    assert a.method == "rule:loads"
    assert "Rd = 3.0" in a.text and "Ro" not in a.text


def test_a_topic_word_returns_only_the_values_under_that_topic():
    """Snow and seismic values are both 'loads', but a snow question must not show the seismic
    clause, nor the other way round."""
    snow = answer("What is the design snow load?", criteria_index(), llm=None)
    assert snow.method == "rule:loads"
    assert "Ss = 1.9 kPa" in snow.text and "Rd" not in snow.text

    seismic = answer("What is the seismic force?", criteria_index(), llm=None)
    assert seismic.method == "rule:loads"
    assert "Rd = 3.0" in seismic.text and "Ss" not in seismic.text


def no_loads_index() -> Index:
    """A small steel set that states member sizes, a note and a level, but no force or load."""
    return make_index(
        make_fact("S-101.note.001", "note", "ALL DIMENSIONS ARE IN MILLIMETRES.", "S-101", number="1"),
        make_fact("S-101.label.001", "label", "L102X102X9.5", "S-101", family="L", orientation="diagonal"),
        make_fact("S-101.elevation.001", "elevation", "1200", "S-101", name="T.O. LOADING DOCK"),
    )


def test_a_set_with_no_loads_says_so_explicitly():
    """When no force or load value appears anywhere, a load question gets a plain 'none stated'
    answer above the threshold, not the generic not-found text or an unrelated member listing."""
    idx = no_loads_index()
    for q in ("Are there any forces shown?", "What is the brace force?", "What are the design loads?"):
        a = answer(q, idx, llm=None)
        assert a.method == "rule:no-loads", q
        assert a.confidence >= THRESHOLD
        assert a.fact_ids == []
        assert "No member forces or design loads are stated on this drawing set" in a.text


def test_a_word_that_only_contains_load_is_not_a_load_question():
    """'Loading dock' is a place, not a load: its level is still answered from the level marker."""
    a = answer("What is the loading dock elevation?", no_loads_index(), llm=None)
    assert a.method == "rule:elevations"
    assert "1200" in a.text


def test_no_loads_answer_is_not_given_when_a_load_value_exists():
    """A stated design value is answered by the loads rule, never hidden behind 'none stated'."""
    idx = make_index(make_fact("S-001.note.001", "note", "a. Ss = 1.9 kPa", "S-001", heading="Snow Loads"))
    assert answer("What is the design snow load?", idx, llm=None).method == "rule:loads"


def test_no_loads_answer_is_not_given_when_the_text_mentions_forces():
    """A note that points to a load schedule is a real mention: the keyword search must show it."""
    idx = make_index(make_fact("S-001.note.001", "note", "FOR BRACE FORCES SEE THE LOAD SCHEDULE", "S-001"))
    assert answer("What are the brace forces?", idx, llm=None).method != "rule:no-loads"


def test_no_loads_answer_is_not_given_for_a_scan_without_text():
    """A scanned set with no extracted text proves nothing about what the sheets state."""
    idx = Index(doc_id="test", source="made_up.pdf", is_vector=False, sheets=[SheetMeta(page=1, number="S-001")])
    assert answer("Are there any loads shown?", idx, llm=None).method != "rule:no-loads"


def test_the_example_set_states_its_loads(platform):
    """The example set tabulates its design loads, so load questions are answered with values."""
    a = answer("What is the live load?", platform, llm=None)
    assert a.method == "rule:loads"
    assert "LIVE LOAD = 4.8 kPa" in a.text and "DEAD LOAD" not in a.text
    assert answer("What are the design loads?", platform, llm=None).method != "rule:no-loads"
