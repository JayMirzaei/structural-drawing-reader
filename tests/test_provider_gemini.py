"""The Gemini provider with the SDK client replaced by a recorder (no network, no key)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from support import reply

pytest.importorskip("google.genai")

from drawing_reader.providers.base import SYSTEM_PROMPT, LLMAnswer
from drawing_reader.providers.gemini import GeminiProvider


class RecordingClient:
    def __init__(self, text=None, error=None):
        self.calls, self._text, self._error = [], text, error
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(text=self._text)


def provider(tmp_path, client) -> GeminiProvider:
    p = GeminiProvider(tmp_path, model="test-model", api_key="test-key-000")
    p._client = client
    return p


def test_without_a_key_the_provider_is_disabled(tmp_path, monkeypatch, idx):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    p = GeminiProvider(tmp_path)
    assert not p.enabled and p.ask("Base plate?", idx) is None


def test_request_shape_and_validated_answer(tmp_path, idx):
    client = RecordingClient(text=json.dumps(reply()))
    p = provider(tmp_path, client)
    a = p.ask("Base plate thickness?", idx)
    assert a.method == "llm:gemini" and a.fact_ids == ["S-501.note.001"] and p.calls == 1

    call = client.calls[0]
    assert call["model"] == "test-model"
    config = call["config"]
    assert config.system_instruction == SYSTEM_PROMPT and config.response_mime_type == "application/json"
    assert config.response_schema is LLMAnswer
    parts = call["contents"][0].parts
    assert parts[0].text.startswith("FACT INDEX") and '<sheet_text sheet="S-501"' in parts[0].text
    assert parts[1].text == "Image of sheet S-501:" and parts[2].inline_data.mime_type == "image/jpeg"
    assert parts[-1].text == "QUESTION: Base plate thickness?"

    assert p.ask("Base plate thickness?", idx).method == "llm:gemini (cached)" and len(client.calls) == 1


def test_a_failed_call_is_an_error_answer(tmp_path, idx):
    p = provider(tmp_path, RecordingClient(error=RuntimeError("429 quota exceeded for test-key-000")))
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "429" in a.text and "test-key-000" not in a.caveats[0]
