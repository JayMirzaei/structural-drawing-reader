"""The local provider on a full-size index: the fact budget, the stable prompt prefix, and answer
validation through a whole `ask`, on the synthetic example set and a fake server (no model, no
network). The unit-level checks of the same logic are in the other provider tests."""

from __future__ import annotations

import json as jsonlib

import pytest

from drawing_reader.providers import local
from drawing_reader.providers.base import FACT_BUDGET_CHARS, fact_line, select_facts
from drawing_reader.providers.local import LocalProvider
from support import reply

SHEETS = ["S-301", "S-001"]
GROUT_NOTE = "S-301.note.002"  # "25 NON-SHRINK GROUT UNDER PLATE"


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeServer:
    """Stands in for the `httpx` module inside the provider: one loaded model, a scripted reply."""

    def __init__(self, model_reply):
        self.model_reply, self.posts = model_reply, []

    def get(self, url, timeout=None):
        return FakeResponse({"model_path": "/models/Example-8B-Q4.gguf", "modalities": {"vision": False}})

    def post(self, url, json=None, timeout=None):
        self.posts.append(json)
        return FakeResponse({"choices": [{"message": {"content": jsonlib.dumps(self.model_reply)}}]})


@pytest.fixture
def provider(monkeypatch, tmp_path):
    """`provider(model_reply)` -> (fake server, a LocalProvider talking to it)."""

    def start(model_reply=None):
        fake = FakeServer(model_reply or reply())
        monkeypatch.setattr(local, "httpx", fake)
        return fake, LocalProvider(tmp_path)

    return start


def test_the_grout_note_is_where_these_tests_expect_it(platform):
    assert platform.get(GROUT_NOTE).value == "25 NON-SHRINK GROUT UNDER PLATE"


def test_facts_of_two_real_sheets_are_cut_to_the_budget_in_id_order(platform):
    """Two sheets of a typical set hold more facts than a small context window takes: the selection
    stops at the character budget and never depends on the question."""
    on_sheets = [f for f in platform.facts if f.sheet in SHEETS]
    chosen, hinted = select_facts(platform, SHEETS, None)
    assert 0 < len(chosen) < len(on_sheets) and hinted == []
    assert [f.id for f in chosen] == sorted(f.id for f in chosen)
    assert sum(len(fact_line(f)) + 1 for f in chosen) <= FACT_BUDGET_CHARS
    small, _ = select_facts(platform, SHEETS, None, budget=300)
    assert 0 < len(small) < len(chosen)


def test_hinted_facts_are_quoted_even_from_a_sheet_that_was_not_picked(platform):
    """Rule hits are handed to the model in full, wherever they are; an id that does not exist is
    dropped."""
    other = next(f for f in platform.facts if f.sheet == "S-101")
    chosen, _ = select_facts(platform, SHEETS, None)
    _, hinted = select_facts(platform, SHEETS, [other.id, chosen[0].id, "S-9.bogus.001"])
    assert hinted == [other, chosen[0]]


def test_the_prompt_prefix_is_the_same_for_every_question_about_the_same_sheets(provider, platform):
    """The server caches the prompt prefix, so the question and the hints must come after the sheet
    facts."""
    _, p = provider()
    first = p.messages("What is the grout thickness?", platform, SHEETS, None)[1]["content"]
    second = p.messages("Anchor rod diameter?", platform, SHEETS, ["S-001.note.001"])[1]["content"]
    prefix = first.split("\nQUESTION:")[0]
    assert len(prefix) > 1000 and second.startswith(prefix)


def test_clearing_the_cache_makes_the_next_question_call_the_server_again(provider, platform):
    fake, p = provider(reply(answer="25 mm of grout.", cited=[GROUT_NOTE]))
    p.ask("Grout thickness?", platform)
    assert p.ask("Grout thickness?", platform).method.endswith("(cached)")
    assert (p.calls, len(fake.posts)) == (1, 1)
    assert p.clear_cache() == 1
    assert not p.ask("Grout thickness?", platform).method.endswith("(cached)")
    assert (p.calls, len(fake.posts)) == (2, 2)


def test_a_reply_citing_a_real_and_an_invented_fact_keeps_only_the_real_one(provider, platform):
    _, p = provider(reply(answer="25 mm of grout.", cited=[GROUT_NOTE, "S-9.bogus.001"]))
    a = p.ask("Grout thickness?", platform)
    assert a.fact_ids == [GROUT_NOTE] and a.confidence == 0.9
    assert any("did not exist" in c for c in a.caveats)


def test_an_uncited_reply_is_capped_whatever_confidence_the_model_claims(provider, platform):
    _, p = provider(reply(answer="Probably thick enough.", cited=[], confidence=0.95))
    a = p.ask("Base plate?", platform)
    assert a.confidence <= 0.6 and any("no verifiable facts" in c for c in a.caveats)


def test_a_number_the_cited_fact_does_not_contain_is_flagged(provider, platform):
    """The model cites the grout note but adds a second thickness from nowhere: the unsupported
    number is named, the supported one is not, and the confidence is cut."""
    text = "The grout is 25 mm and the levelling plate is 12.7 mm thick."
    _, p = provider(reply(answer=text, cited=[GROUT_NOTE], confidence=0.95))
    a = p.ask("Grout and levelling plate?", platform)
    flagged = next(c for c in a.caveats if "do not appear" in c)
    assert a.confidence <= 0.5
    assert "12.7" in flagged and "25" not in flagged.split("facts:")[-1]
