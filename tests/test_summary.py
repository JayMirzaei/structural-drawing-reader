"""The first-look helpers: sheet ordering and the advice shown about the scope of a set."""

from __future__ import annotations

from drawing_reader.qa import scope_advice
from drawing_reader.qa.answer import sheet_sort_key
from drawing_reader.schema import SheetMeta
from support import make_index


def _set_of(numbers):
    """An index of sheets with the given numbers; None stands for a sheet whose number was not read
    (it keeps its page placeholder "P<n>")."""
    metas = [SheetMeta(page=i, number=n or f"P{i}", width=1224, height=792) for i, n in enumerate(numbers, 1)]
    return make_index(sheets=metas)


def test_dotted_sheet_numbers_sort_by_number_not_by_text():
    """ "D.1.4.10" comes after "D.1.4.9": each segment is compared as a number."""
    numbers = ["D.1.4.10", "D.1.4.9", "D.1.4.11", "D.1.4.3"]
    assert sorted(numbers, key=sheet_sort_key) == ["D.1.4.3", "D.1.4.9", "D.1.4.10", "D.1.4.11"]


def test_dashed_sheet_numbers_sort_by_number_not_by_text():
    """ "S4-12" comes after "S4-3", and both after "S2-7"."""
    assert sorted(["S4-12", "S4-3", "S2-7"], key=sheet_sort_key) == ["S2-7", "S4-3", "S4-12"]


def test_scope_advice_does_not_count_unread_sheets_as_a_discipline():
    """A set that is almost all one prefix is not multi-discipline: the "P" placeholders of unread
    sheets are not a discipline, and a handful of sheets with another prefix do not make it mixed."""
    one_prefix = _set_of([f"D.1.4.{i}" for i in range(1, 40)] + [None] * 11 + ["C.6.2.1"] * 4)
    assert not any("multi-discipline" in note for note in scope_advice(one_prefix))


def test_scope_advice_flags_a_set_with_several_disciplines():
    """Structural, architectural and mechanical sheets together are called multi-discipline."""
    mixed = _set_of(["S02-01"] * 3 + ["A02-01"] * 4 + ["M02-01"] * 4)
    assert any("multi-discipline" in note for note in scope_advice(mixed))
