"""The Anthropic provider through the real SDK, with the HTTP transport mocked (no network, no key)."""

from __future__ import annotations

import json

import pytest

from support import reply

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")

from drawing_reader.providers.anthropic import FALLBACK_BETA, AnthropicProvider  # noqa: E402
from drawing_reader.providers.base import SYSTEM_PROMPT  # noqa: E402


def message(text, stop_reason="end_turn", **extra) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": [{"type": "text", "text": text}] if text is not None else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        **extra,
    }


def provider(tmp_path, respond, **kwargs) -> tuple[AnthropicProvider, list]:
    requests: list = []

    def handler(request):
        requests.append(request)
        status, body = respond(request)
        return httpx2.Response(status, json=body)

    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicProvider(tmp_path, api_key="sk-ant-test-000", http_client=client, **kwargs), requests


def test_without_a_key_the_provider_is_disabled(tmp_path, monkeypatch, idx):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = AnthropicProvider(tmp_path)
    assert not p.enabled and p.ask("Base plate?", idx) is None


def test_request_shape_and_validated_answer(tmp_path, idx):
    p, requests = provider(tmp_path, lambda r: (200, message(json.dumps(reply()))), model="test-model")
    a = p.ask("Base plate thickness?", idx)
    assert a.method == "llm:anthropic" and a.fact_ids == ["S-501.note.001"] and p.calls == 1

    request = requests[0]
    assert request.url.path == "/v1/messages"
    assert FALLBACK_BETA not in request.headers.get("anthropic-beta", "")  # the beta is opt-in
    body = json.loads(request.content)
    assert body["model"] == "test-model" and body["system"] == SYSTEM_PROMPT and "fallbacks" not in body
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(body)  # current models reject or ignore these
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"answer", "cited_fact_ids", "sheets_used", "confidence", "caveats"}

    content = body["messages"][0]["content"]
    assert [block["type"] for block in content] == ["text", "text", "image", "text"]
    assert content[0]["text"].startswith("FACT INDEX") and content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[2]["source"]["media_type"] == "image/jpeg" and content[2]["source"]["type"] == "base64"
    assert content[3]["text"].endswith("QUESTION: Base plate thickness?")
    assert "cache_control" not in content[3]  # the part that changes per question stays after the breakpoint

    assert p.ask("Base plate thickness?", idx).method == "llm:anthropic (cached)" and len(requests) == 1


def test_refusal_fallbacks_are_sent_only_when_opted_in(tmp_path, idx, monkeypatch):
    monkeypatch.setenv("DRAWING_READER_ANTHROPIC_FALLBACKS", "1")
    p, requests = provider(tmp_path, lambda r: (200, message(json.dumps(reply()))))
    assert p.ask("Base plate thickness?", idx).method == "llm:anthropic"
    assert json.loads(requests[0].content)["fallbacks"] == "default"
    assert FALLBACK_BETA in requests[0].headers["anthropic-beta"]


@pytest.mark.parametrize("value", ["", "0", "off"])
def test_refusal_fallbacks_stay_off_for_any_other_value(tmp_path, idx, monkeypatch, value):
    monkeypatch.setenv("DRAWING_READER_ANTHROPIC_FALLBACKS", value)
    p, requests = provider(tmp_path, lambda r: (200, message(json.dumps(reply()))))
    assert p.ask("Base plate thickness?", idx).method == "llm:anthropic"
    assert "fallbacks" not in json.loads(requests[0].content)


def test_a_refusal_is_an_error_answer(tmp_path, idx):
    refusal = message(
        None, stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}
    )
    p, _ = provider(tmp_path, lambda r: (200, refusal))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "declined" in a.caveats[0]


def test_a_reply_cut_short_is_an_error_answer(tmp_path, idx):
    p, _ = provider(tmp_path, lambda r: (200, message('{"answer": "The', stop_reason="max_tokens")))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "cut short" in a.caveats[0]


def test_a_rejected_key_is_reported_without_the_key(tmp_path, idx):
    error = {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key sk-ant-test-000"}}
    p, _ = provider(tmp_path, lambda r: (401, error))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "the API key was rejected" in a.text
    assert "sk-ant-test-000" not in a.caveats[0]
