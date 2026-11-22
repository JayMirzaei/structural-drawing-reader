"""A model on your own machine, through an OpenAI-compatible server (llama.cpp `llama-server`, Ollama).

Nothing leaves the machine, which matters when drawings must stay private. The differences
from the hosted providers are all forced by a small context window (the full fact index of even a
five-sheet set can exceed 16k tokens):

* The model gets a subset of the index: every fact on the two picked sheets, in fixed id order, within
  a character budget, then the rule-hinted facts from other sheets. The fixed order keeps the prompt
  prefix identical across questions about the same sheets, so the server's prompt cache makes
  follow-up questions much cheaper than the first one.
* Facts are written as terse lines, not JSON.
* The reply is constrained to the `LLMAnswer` JSON schema by the server, so it always parses.
* Sheet images are attached only when the server reports that the loaded model can see.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from drawing_reader import settings
from drawing_reader.providers.base import (
    FACT_BUDGET_CHARS,
    SYSTEM_PROMPT,
    BaseProvider,
    LLMAnswer,
    budgeted_prompt_text,
    fact_line,
    select_facts,
    sheet_images,
    unsupported_numbers,
)
from drawing_reader.schema import Index

__all__ = ["FACT_BUDGET_CHARS", "LocalProvider", "fact_line", "select_facts", "unsupported_numbers"]

PROBE_TIMEOUT_S = 2
CALL_TIMEOUT_S = 300  # a first question on a CPU-only machine can take minutes
MAX_ANSWER_TOKENS = 600
IMAGE_MAX_W = 1024


class LocalProvider(BaseProvider):
    """Talks to `<base_url>/v1/chat/completions`. The server is probed once, at construction."""

    name = "local"
    cache_subdir = "llm_local"

    def __init__(self, cache_dir: str | Path, base_url: str | None = None, model: str | None = None):
        super().__init__(cache_dir, model or settings.local_model())
        self.base_url = (base_url or settings.local_url()).rstrip("/")
        self.vision = False
        self._send_model = bool(self.model)  # a multi-model server (Ollama) needs the model named in each request
        probed = self._probe()
        self.model = self.model or probed or "local"
        self.enabled = self.last_error is None

    @property
    def label(self) -> str:
        return f"llm:local ({self.model})"

    def _probe(self) -> str | None:
        """Name of the model the server will use, or None (with `last_error` set) if it is not running.

        llama.cpp reports its one loaded model at `/props`; other OpenAI-compatible servers list
        theirs at `/v1/models`, and the first is taken unless a model was configured."""
        try:
            response = httpx.get(f"{self.base_url}/props", timeout=PROBE_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001  any failure means "not usable now"
            self.last_error = f"local model server not reachable at {self.base_url} ({type(e).__name__})"
            return None
        try:
            props = response.json()
        except ValueError:
            props = None  # not llama.cpp: the endpoint does not exist there
        if isinstance(props, dict) and "model_path" in props:
            self.vision = bool(props.get("modalities", {}).get("vision"))
            return Path(props.get("model_path", "")).name.removesuffix(".gguf") or "local"
        try:
            listed = httpx.get(f"{self.base_url}/v1/models", timeout=PROBE_TIMEOUT_S).json()
            first = listed["data"][0]["id"]
        except Exception:  # noqa: BLE001  the server is up but does not list models: use it as it is
            return None
        self._send_model = True
        return first

    def messages(self, question: str, idx: Index, sheets: list[str], hint_ids: list[str] | None) -> list[dict]:
        """The chat messages for one question (system prompt, then the budgeted user turn)."""
        text = budgeted_prompt_text(question, idx, sheets, hint_ids)
        content: str | list[dict] = text
        if self.vision:
            parts: list[dict] = [{"type": "text", "text": text}]
            for image in sheet_images(idx, sheets, max_w=IMAGE_MAX_W):
                url = "data:image/jpeg;base64," + base64.b64encode(image.jpeg).decode()
                parts.append({"type": "text", "text": f"Image of sheet {image.sheet}:"})
                parts.append({"type": "image_url", "image_url": {"url": url}})
            content = parts
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]

    def payload(self, messages: list[dict]) -> dict:
        """The request body: greedy decoding (same facts, same answer) and a schema-constrained reply."""
        body = {
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": MAX_ANSWER_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "LLMAnswer", "schema": LLMAnswer.model_json_schema()},
            },
            "chat_template_kwargs": {"enable_thinking": False},  # llama.cpp: skip the reasoning phase of hybrid models
        }
        if self._send_model:
            body["model"] = self.model
        return body

    def _complete(self, question: str, idx: Index, sheets: list[str], hint_ids: list[str] | None) -> str:
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=self.payload(self.messages(question, idx, sheets, hint_ids)),
            timeout=CALL_TIMEOUT_S,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"] or "{}"

    def failure_text(self, error: Exception) -> str:
        return "The local model call failed. Is the local model server running? Rule-based answers still work."

    def prewarm(self, idx: Index, sheets: list[str]) -> None:
        """Push the prompt prefix for `sheets` through the server with no output, so the first real
        question about those sheets finds its prefix in the server's prompt cache. Best effort."""
        if not self.enabled:
            return
        body = self.payload(self.messages("", idx, sheets, None))
        body.pop("response_format")
        body.pop("temperature")
        body["max_tokens"] = 1
        try:
            httpx.post(f"{self.base_url}/v1/chat/completions", json=body, timeout=CALL_TIMEOUT_S)
        except Exception:  # noqa: BLE001  warming up is optional
            return
