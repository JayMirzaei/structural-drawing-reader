"""The local provider against a fake OpenAI-compatible server (no model, no network)."""

from __future__ import annotations

import json as jsonlib

import pytest

from drawing_reader.providers import local
from drawing_reader.providers.local import LocalProvider
from support import reply


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeServer:
    """Stands in for the `httpx` module inside the provider. `kind` selects what the server looks like."""

    def __init__(self, kind="llama.cpp", model_reply=None):
        self.kind, self.model_reply, self.gets, self.posts = kind, model_reply or reply(), [], []

    def get(self, url, timeout=None):
        self.gets.append(url)
        if self.kind == "down":
            raise ConnectionError("refused")
        if url.endswith("/props"):
            if self.kind == "llama.cpp":
                return FakeResponse({"model_path": "/models/Example-8B-Q4.gguf", "modalities": {"vision": False}})
            return FakeResponse(ValueError("404 page not found"), status=404)
        if self.kind == "bare":
            return FakeResponse(ValueError("no such route"), status=404)
        return FakeResponse({"data": [{"id": "example:8b"}, {"id": "other:1b"}]})

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return FakeResponse({"choices": [{"message": {"content": jsonlib.dumps(self.model_reply)}}]})


@pytest.fixture
def server(monkeypatch):
    def start(kind="llama.cpp", model_reply=None):
        fake = FakeServer(kind, model_reply)
        monkeypatch.setattr(local, "httpx", fake)
        return fake

    return start


def test_server_down_disables_the_provider(server, idx, tmp_path):
    server("down")
    p = LocalProvider(tmp_path)
    assert not p.enabled and "not reachable" in p.last_error
    assert p.ask("Base plate thickness?", idx) is None


def test_llama_cpp_probe_reads_the_loaded_model(server, tmp_path):
    fake = server()
    p = LocalProvider(tmp_path, base_url="http://localhost:9999/")
    assert p.enabled and p.model == "Example-8B-Q4" and p.vision is False
    assert p.label == "llm:local (Example-8B-Q4)" and fake.gets == ["http://localhost:9999/props"]
    assert "model" not in p.payload([])  # a single-model server needs no model name


def test_other_servers_are_probed_through_the_models_list(server, tmp_path):
    server("ollama")
    p = LocalProvider(tmp_path)
    assert p.enabled and p.model == "example:8b" and p.payload([])["model"] == "example:8b"
    configured = LocalProvider(tmp_path, model="other:1b")
    assert configured.model == "other:1b" and configured.payload([])["model"] == "other:1b"


def test_a_server_that_lists_nothing_is_still_used(server, tmp_path):
    server("bare")
    p = LocalProvider(tmp_path)
    assert p.enabled and p.model == "local"


def test_payload_constrains_the_reply_to_the_answer_schema(server, idx, tmp_path):
    server()
    p = LocalProvider(tmp_path)
    messages = p.messages("Base plate?", idx, ["S-501"], None)
    assert [m["role"] for m in messages] == ["system", "user"] and isinstance(messages[1]["content"], str)
    body = p.payload(messages)
    assert body["temperature"] == 0.0 and body["response_format"]["type"] == "json_schema"
    assert "cited_fact_ids" in body["response_format"]["json_schema"]["schema"]["properties"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_images_are_attached_only_when_the_model_can_see(server, idx, tmp_path):
    server()
    p = LocalProvider(tmp_path)
    p.vision = True
    content = p.messages("Base plate?", idx, ["S-101", "S-501"], None)[1]["content"]
    kinds = [part["type"] for part in content]
    assert kinds == ["text", "text", "image_url"] and content[1]["text"] == "Image of sheet S-501:"
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_ask_validates_citations_and_caches(server, idx, tmp_path):
    fake = server(model_reply=reply(cited=["S-501.note.001", "S-9.bogus.001"]))
    p = LocalProvider(tmp_path)
    a = p.ask("Base plate thickness?", idx)
    assert a.fact_ids == ["S-501.note.001"] and any("did not exist" in c for c in a.caveats)
    assert a.method == "llm:local (Example-8B-Q4)" and p.calls == 1
    assert fake.posts[0][0] == "http://127.0.0.1:8080/v1/chat/completions"
    again = p.ask("Base plate thickness?", idx)
    assert again.method.endswith("(cached)") and p.calls == 1 and len(fake.posts) == 1
    assert p.clear_cache() == 1


def test_a_failed_call_is_an_error_answer(server, idx, tmp_path, monkeypatch):
    fake = server()
    p = LocalProvider(tmp_path)

    def timeout(*args, **kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr(fake, "post", timeout)
    a = p.ask("Base plate?", idx)
    assert a.method == "llm:error" and "TimeoutError" in a.caveats[0] and "local model" in a.text


def test_prewarm_sends_the_prefix_and_asks_for_one_token(server, idx, tmp_path):
    fake = server()
    p = LocalProvider(tmp_path)
    p.prewarm(idx, ["S-501"])
    _, body = fake.posts[0]
    assert body["max_tokens"] == 1 and "response_format" not in body
    assert body["messages"][1]["content"].endswith("QUESTION: ")
    assert p.calls == 0
