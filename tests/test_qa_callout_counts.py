"""'How many callouts ...' questions: callouts drawn on a sheet, callouts pointing at a sheet, and
callouts pointing at a detail described by its title.

On the example set the framing plan S-101 carries four detail bubbles and the elevations S-201
carry three; they point at S-201 and S-301. The other sheets carry none. A detail named in note text
('SEE DETAIL 3/S-301') counts as pointing at it too, so those tests look at the drawn bubbles."""

from __future__ import annotations

import pytest

from drawing_reader.qa import answer


def cited_bubbles(a, idx):
    """The drawn callouts an answer cites (leaving out details mentioned in note text)."""
    return [f for f in map(idx.get, a.fact_ids) if f.kind == "callout"]


def test_callouts_on_a_sheet_counts_the_sheet_they_are_drawn_on(platform):
    """'How many callouts are on <sheet>?' counts the bubbles drawn on that sheet, not the bubbles
    on other sheets that point at it (two point at S-201, three are drawn on it)."""
    a = answer("How many callouts are on S-201?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert a.text.startswith("3 callout(s) on S-201")
    assert len(a.fact_ids) == 3
    assert all(platform.get(fid).sheet == "S-201" for fid in a.fact_ids)
    assert "1/S-201" not in a.text and "2/S-201" not in a.text


def test_callouts_on_a_sheet_that_nothing_points_at(platform):
    a = answer("How many callouts are on S-101?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert a.text.startswith("4 callout(s) on S-101")


def test_how_many_callouts_does_a_sheet_have(platform):
    """The same count asked with 'does ... have', and with 'detail callouts'."""
    a = answer("How many detail callouts does S-201 have?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert a.text.startswith("3 callout(s) on S-201")


def test_on_a_sheet_and_reference_a_sheet_are_different_counts(platform):
    """The details sheet draws no bubble of its own, and five bubbles elsewhere point at it. The
    count in the answer is the number of things it cites."""
    drawn = answer("How many callouts on S-301?", platform, llm=None)
    assert drawn.method == "rule:callouts"
    assert drawn.text == "0 callout(s) on S-301."

    pointing = answer("How many callouts reference S-301?", platform, llm=None)
    assert pointing.method == "rule:callouts"
    assert pointing.text.startswith(f"{len(pointing.fact_ids)} callout(s) reference S-301")
    assert len(cited_bubbles(pointing, platform)) == 5
    assert all(f.attrs["target_sheet"] == "S-301" for f in map(platform.get, pointing.fact_ids))


def test_callouts_that_reference_a_detail_named_by_its_title(platform):
    """A detail described in words, with no sheet or detail number, is matched to the view with
    that title; the count is of the callouts that point at that view. One bubble points at the
    brace gusset detail."""
    a = answer("How many callouts reference the brace gusset?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert a.text.startswith(f"{len(a.fact_ids)} callout(s) reference the brace gusset")
    assert [f.value for f in cited_bubbles(a, platform)] == ["3/S-301"]
    assert all(f.attrs["detail"] == "3" for f in map(platform.get, a.fact_ids))


def test_a_view_that_no_callout_points_at_counts_zero(platform):
    """Nothing points at the framing plan itself. The answer is a count of zero, not a listing of
    every callout in the set."""
    a = answer("How many callouts reference the steel framing plan?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert "0 callout(s)" in a.text
    assert a.fact_ids == []


@pytest.mark.xfail(
    strict=True,
    reason="the title match needs every content word of the question in the view title; the generic "
    "word 'detail' is not in 'COLUMN BASE PLATE', so the rule falls through to listing every callout",
)
def test_the_word_detail_does_not_break_the_title_match(platform):
    """'The base plate detail' describes the view titled COLUMN BASE PLATE: two bubbles point at it."""
    a = answer("How many callouts reference the base plate detail?", platform, llm=None)
    assert a.method == "rule:callouts"
    assert a.text.startswith(f"{len(a.fact_ids)} callout(s) reference the column base plate")
    assert [f.value for f in cited_bubbles(a, platform)] == ["1/S-301", "1/S-301"]
