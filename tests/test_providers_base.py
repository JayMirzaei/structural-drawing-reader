"""The shared provider logic: prompt building, citation and number validation, the cache, the ask flow."""

from __future__ import annotations

import json

import pytest

from drawing_reader.providers.base import (
    AnswerCache,
    BaseProvider,
    LLMAnswer,
    Provider,
    budgeted_prompt_text,
    fact_line,
    full_prompt,
    pick_sheets,
    redact,
    select_facts,
    strict_json_schema,
    to_answer,
    unsupported_numbers,
)
from drawing_reader.qa import answer
from support import reply


class ScriptedProvider(BaseProvider):
    """A provider whose model reply is whatever the test hands it."""

    name = "scripted"
    cache_subdir = "llm_scripted"

    def __init__(self, cache_dir, raw=None, error=None, api_key=None):
        super().__init__(cache_dir, "model-x", api_key)
        self.raw, self.error, self.seen = raw, error, []

    def _complete(self, question, idx, sheets, hint_ids):
        self.seen.append((question, sheets, hint_ids))
        if self.error:
            raise self.error
        return self.raw


def test_strict_schema_requires_every_property_and_forbids_extras():
    schema = strict_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == set(LLMAnswer.model_fields)
    assert not any("default" in spec or "title" in spec for spec in schema["properties"].values())
    assert schema["properties"]["cited_fact_ids"]["type"] == "array"


def test_pick_sheets_prefers_a_title_match_and_a_named_sheet(idx):
    assert pick_sheets("base plate thickness", idx)[0] == "S-501"
    assert pick_sheets("what does S-101 say about base plates?", idx)[0] == "S-101"
    assert len(pick_sheets("anything", idx, n=1)) == 1


def test_fact_line_has_seven_fields(idx):
    parts = fact_line(idx.facts[0]).split(" | ")
    assert len(parts) == 7 and parts[0] == "S-101.note.001" and parts[1] == "note" and parts[4] == "S-101"
    assert "heading=General Notes" in parts[6]


def test_select_facts_order_budget_and_hints(idx):
    chosen, hinted = select_facts(idx, ["S-501"], ["S-101.note.002", "S-501.note.001", "S-9.bogus.001"])
    assert [f.id for f in chosen] == sorted(f.id for f in idx.facts if f.sheet == "S-501")
    assert [f.id for f in hinted] == ["S-101.note.002", "S-501.note.001"]  # unknown ids dropped, order kept
    small, _ = select_facts(idx, ["S-501"], None, budget=len(fact_line(chosen[0])) + 2)
    assert [f.id for f in small] == [chosen[0].id]


def test_budgeted_prompt_prefix_does_not_depend_on_the_question(idx):
    a = budgeted_prompt_text("Grout thickness?", idx, ["S-501"], None)
    b = budgeted_prompt_text("Anchor rods?", idx, ["S-501"], ["S-101.note.001"])
    prefix = a.split("\nQUESTION:")[0]
    assert b.startswith(prefix) and b.endswith("QUESTION: Anchor rods?")
    assert "MOST RELEVANT FACTS" in b and "MOST RELEVANT FACTS" not in a


def test_full_prompt_carries_index_sheet_text_hints_and_images(idx):
    prompt = full_prompt("Base plate?", idx, ["S-101", "S-501"], ["S-501.note.001"])
    lines = prompt.index_text.splitlines()
    assert lines[:2] == ["FACT INDEX (one JSON per line):", "<fact_index>"] and lines[-1] == "</fact_index>"
    assert len(lines) == len(idx.facts) + 3  # header, fence, one JSON line per fact, fence
    assert json.loads(lines[2])["id"] == "S-101.note.001"
    assert '<sheet_text sheet="S-501" title="BASE PLATE DETAILS">' in prompt.context_text
    assert "S-501.note.001" in prompt.context_text
    assert [i.sheet for i in prompt.images] == ["S-501"] and prompt.images[0].jpeg[:2] == b"\xff\xd8"
    assert prompt.question_text == "QUESTION: Base plate?"


def test_unsupported_numbers_ignores_sheet_numbers_and_fact_ids(idx):
    fact = idx.get("S-501.note.001")
    assert unsupported_numbers("It is 38 mm thick (38.0mm).", [fact]) == []
    assert unsupported_numbers("It is 22.2 mm.", [fact]) == ["22.2"]
    assert unsupported_numbers("38mm on S-501 (S-501.note.001); see 2/S-501 and sheet S01-02.", [fact, None]) == []


def test_to_answer_drops_ids_that_are_not_in_the_index(idx):
    la = LLMAnswer(**reply(cited=["S-501.note.001", "S-9.bogus.001"]))
    a = to_answer(la, idx, "llm:test")
    assert a.fact_ids == ["S-501.note.001"] and a.confidence == 0.9 and a.method == "llm:test"
    assert any("did not exist" in c for c in a.caveats)


def test_to_answer_caps_an_uncited_answer(idx):
    a = to_answer(LLMAnswer(**reply(answer="Probably thick.", cited=[], confidence=0.95)), idx, "llm:test")
    assert a.confidence == 0.6 and any("no verifiable facts" in c for c in a.caveats)


def test_to_answer_flags_numbers_the_cited_facts_do_not_contain(idx):
    la = LLMAnswer(**reply(answer="The base plate is 38mm and the cap plate is 44.5mm thick.", confidence=0.95))
    a = to_answer(la, idx, "llm:test", cached=True)
    assert a.confidence == 0.5 and a.method == "llm:test (cached)"
    flagged = next(c for c in a.caveats if "do not appear" in c)
    assert "44.5" in flagged and "38" not in flagged.split("facts:")[-1]


def test_answer_cache_round_trip_clear_and_damaged_entry(tmp_path):
    cache = AnswerCache(tmp_path / "answers")
    key = ("model-x", "doc123", " Base plate? ", ["S-501"])
    assert cache.get(*key) is None and not (tmp_path / "answers").exists()  # nothing is created until a write
    cache.put(*key, LLMAnswer(**reply()))
    assert cache.get("model-x", "doc123", "base plate?", ["S-501"]).answer.startswith("The base plate")
    assert cache.get("model-y", "doc123", "base plate?", ["S-501"]) is None  # the model is part of the key
    cache.path(*key).write_text("{not json")
    assert cache.get(*key) is None
    assert cache.clear() == 1 and cache.clear() == 0


def test_ask_calls_once_then_answers_from_the_cache(idx, tmp_path):
    p = ScriptedProvider(tmp_path, raw=json.dumps(reply()))
    assert isinstance(p, Provider)
    first = p.ask("Base plate thickness?", idx, hint_ids=["S-501.note.001"])
    assert first.method == "llm:scripted" and first.fact_ids == ["S-501.note.001"] and p.calls == 1
    assert p.seen == [("Base plate thickness?", ["S-501", "S-101"], ["S-501.note.001"])]
    again = p.ask("Base plate thickness?", idx)
    assert again.method == "llm:scripted (cached)" and p.calls == 1 and len(p.seen) == 1
    assert p.clear_cache() == 1
    p.ask("Base plate thickness?", idx, sheets=["S-501"])
    assert p.calls == 2 and p.seen[-1][1] == ["S-501"]


def test_ask_returns_none_when_disabled(idx, tmp_path):
    p = ScriptedProvider(tmp_path, raw="{}")
    p.enabled = False
    assert p.ask("Base plate?", idx) is None and p.seen == []


@pytest.mark.parametrize("raw", ["not json at all", '{"answer": 3}'])
def test_a_reply_that_is_not_the_answer_shape_is_an_error_answer(idx, tmp_path, raw):
    p = ScriptedProvider(tmp_path, raw=raw)
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and a.confidence == 0.0 and "ValidationError" in a.caveats[0]
    assert p.cache.clear() == 0  # a bad reply is never cached


def test_a_failed_call_is_an_error_answer_without_the_key(idx, tmp_path):
    p = ScriptedProvider(tmp_path, error=TimeoutError("no reply; key was sk-secret-123"), api_key="sk-secret-123")
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "TimeoutError" in a.caveats[0] and "rule-based answers still work" in a.text
    assert "sk-secret-123" not in a.caveats[0] and "sk-secret-123" not in p.last_error
    assert p.calls == 1  # a failed attempt counts towards the session's call limit
    assert redact("abc", None) == "abc"


def test_router_uses_the_provider_only_when_rules_are_unsure(idx, tmp_path):
    p = ScriptedProvider(tmp_path, raw=json.dumps(reply()))
    confident = answer("What are the column sections?", idx, llm=p)
    assert confident.method == "rule:sections" and p.calls == 0
    unsure = answer("Is the base plate thicker than the grout, and what are the bolts?", idx, llm=p)
    assert unsure.method == "llm:scripted" and unsure.sheets == ["S-501"] and p.calls == 1
    assert p.seen[0][2], "rule hits are passed to the provider as hints"


def test_router_keeps_the_rule_answer_when_the_provider_fails(idx, tmp_path):
    p = ScriptedProvider(tmp_path, error=ConnectionError("down"))
    a = answer("Is the base plate thicker than the grout, and what are the bolts?", idx, llm=p)
    assert a.method.startswith("rule:") and any("the LLM call failed" in c for c in a.caveats)
