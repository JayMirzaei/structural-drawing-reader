"""Anthropic Claude provider (the `anthropic` extra), through the Messages API with structured output."""

from __future__ import annotations

import base64
from pathlib import Path

from drawing_reader import settings
from drawing_reader.providers.base import SYSTEM_PROMPT, BaseProvider, ProviderError, full_prompt, strict_json_schema
from drawing_reader.schema import Index

DEFAULT_MODEL = "claude-opus-5-5"  # DRAWING_READER_ANTHROPIC_MODEL overrides it
MAX_TOKENS = 16000  # room for the model's reasoning as well as the short JSON answer
EFFORT = "medium"  # a lookup over given facts; set explicitly because the default differs between models
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(BaseProvider):
    """Sends the whole fact index, the picked sheets' images and text.

    * The fact index is the first content block and carries a cache breakpoint: it is the same for
      every question about a document, so follow-up questions read it from the prompt cache.
    * The reply is constrained to the `LLMAnswer` schema with `output_config.format`.
    * No sampling or thinking parameters are sent: current models reject them and think adaptively.
    * Server-side refusal fallbacks are off by default. They are a beta feature
      (`server-side-fallback-2026-07-01`): if the model declines a request, the API re-runs it on a
      fallback model inside the same call. Set DRAWING_READER_ANTHROPIC_FALLBACKS=1 to opt in; the
      request then goes to the beta Messages endpoint with `fallbacks="default"`.
    """

    name = "anthropic"
    cache_subdir = "llm_anthropic"

    def __init__(self, cache_dir: str | Path, model: str | None = None, api_key: str | None = None, http_client=None):
        super().__init__(cache_dir, model or settings.model_for(self.name, DEFAULT_MODEL), api_key)
        self.enabled = bool(api_key)  # the registry reads the key from the environment
        self.use_fallbacks = settings.anthropic_fallbacks()
        self._http_client = http_client  # tests pass a client with a mock transport
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self._api_key, http_client=self._http_client)
        return self._client

    def _complete(self, question: str, idx: Index, sheets: list[str], hint_ids: list[str] | None) -> str:
        prompt = full_prompt(question, idx, sheets, hint_ids)
        content: list[dict] = [{"type": "text", "text": prompt.index_text, "cache_control": {"type": "ephemeral"}}]
        for image in prompt.images:
            data = base64.standard_b64encode(image.jpeg).decode()
            content.append({"type": "text", "text": f"Image of sheet {image.sheet}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
        content.append({"type": "text", "text": f"{prompt.context_text}\n\n{prompt.question_text}"})
        request = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": strict_json_schema()}},
        }
        client = self._get_client()
        if self.use_fallbacks:
            response = client.beta.messages.create(**request, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            response = client.messages.create(**request)
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise ProviderError("the model declined to answer" + (f" ({category})" if category else ""))
        if response.stop_reason == "max_tokens":
            raise ProviderError("the reply was cut short before the JSON was complete")
        return next((block.text for block in response.content if block.type == "text"), "{}")

    def failure_text(self, error: Exception) -> str:
        import anthropic

        if isinstance(error, anthropic.AuthenticationError):
            reason = "the API key was rejected"
        elif isinstance(error, anthropic.RateLimitError):
            reason = "rate limit reached"
        elif isinstance(error, anthropic.APIConnectionError):
            reason = "the API could not be reached"
        else:
            reason = type(error).__name__
        return f"The Claude call failed ({reason}); rule-based answers still work."
