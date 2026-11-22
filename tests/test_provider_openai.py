"""The OpenAI provider through the real SDK, with the HTTP transport mocked (no network, no key)."""

from __future__ import annotations

import json

import pytest

from support import reply

openai = pytest.importorskip("openai")
httpx2 = pytest.importorskip("httpx2")

from drawing_reader.providers.base import SYSTEM_PROMPT  # noqa: E402
from drawing_reader.providers.openai import OpenAIProvider  # noqa: E402


def completion(content, finish_reason="stop", refusal=None) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def provider(tmp_path, respond, **kwargs) -> tuple[OpenAIProvider, list]:
    requests: list = []

    def handler(request):
        requests.append(request)
        status, body = respond(request)
        return httpx2.Response(status, json=body)

    client = openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return OpenAIProvider(tmp_path, api_key="sk-test-key-000", http_client=client, **kwargs), requests


def test_without_a_key_the_provider_is_disabled(tmp_path, monkeypatch, idx):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = OpenAIProvider(tmp_path)
    assert not p.enabled and p.ask("Base plate?", idx) is None


def test_request_shape_and_validated_answer(tmp_path, idx):
    p, requests = provider(tmp_path, lambda r: (200, completion(json.dumps(reply()))), model="test-model")
    a = p.ask("Base plate thickness?", idx)
    assert a.method == "llm:openai" and a.fact_ids == ["S-501.note.001"] and a.confidence == 0.9 and p.calls == 1

    request = requests[0]
    assert request.url.path == "/v1/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == "test-model" and "temperature" not in body
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["additionalProperties"] is False
    system, user = body["messages"]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    kinds = [part["type"] for part in user["content"]]
    assert kinds == ["text", "text", "image_url", "text"]
    assert user["content"][0]["text"].startswith("FACT INDEX") and "S-501.note.001" in user["content"][0]["text"]
    assert user["content"][-1]["text"] == "QUESTION: Base plate thickness?"

    assert p.ask("Base plate thickness?", idx).method == "llm:openai (cached)" and len(requests) == 1


def test_a_refusal_is_an_error_answer(tmp_path, idx):
    p, _ = provider(tmp_path, lambda r: (200, completion(None, refusal="I cannot help with that.")))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "declined" in a.caveats[0]


def test_a_reply_cut_short_is_an_error_answer(tmp_path, idx):
    p, _ = provider(tmp_path, lambda r: (200, completion('{"answer": "The', finish_reason="length")))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "cut short" in a.caveats[0]


def test_a_rejected_key_is_reported_without_the_key(tmp_path, idx):
    error = {"error": {"message": "Incorrect API key provided: sk-test-key-000", "type": "invalid_request_error"}}
    p, _ = provider(tmp_path, lambda r: (401, error))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "the API key was rejected" in a.text
    assert "sk-test-key-000" not in a.caveats[0] and "[key]" in a.caveats[0]
