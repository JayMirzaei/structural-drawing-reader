"""OpenAI provider (the `openai` extra), through the Chat Completions API with a strict JSON schema."""

from __future__ import annotations

import base64
from pathlib import Path

from drawing_reader import settings
from drawing_reader.providers.base import SYSTEM_PROMPT, BaseProvider, ProviderError, full_prompt, strict_json_schema
from drawing_reader.schema import Index

DEFAULT_MODEL = "gpt-5.4-mini"  # DRAWING_READER_OPENAI_MODEL overrides it


class OpenAIProvider(BaseProvider):
    """Sends the whole fact index, the picked sheets' text and their images. No sampling parameters
    are sent: current models reject non-default values."""

    name = "openai"
    cache_subdir = "llm_openai"

    def __init__(self, cache_dir: str | Path, model: str | None = None, api_key: str | None = None, http_client=None):
        super().__init__(cache_dir, model or settings.model_for(self.name, DEFAULT_MODEL), api_key)
        self.enabled = bool(api_key)  # the registry reads the key from the environment
        self._http_client = http_client  # tests pass a client with a mock transport
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=self._api_key, http_client=self._http_client)
        return self._client

    def _complete(self, question: str, idx: Index, sheets: list[str], hint_ids: list[str] | None) -> str:
        prompt = full_prompt(question, idx, sheets, hint_ids)
        content: list[dict] = [{"type": "text", "text": f"{prompt.index_text}\n\n{prompt.context_text}"}]
        for image in prompt.images:
            url = "data:image/jpeg;base64," + base64.b64encode(image.jpeg).decode()
            content.append({"type": "text", "text": f"Image of sheet {image.sheet}:"})
            content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": prompt.question_text})
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "drawing_answer", "strict": True, "schema": strict_json_schema()},
            },
        )
        choice = response.choices[0]
        if choice.message.refusal:
            raise ProviderError(f"the model declined to answer: {choice.message.refusal}")
        if choice.finish_reason == "length":
            raise ProviderError("the reply was cut short before the JSON was complete")
        return choice.message.content or "{}"

    def failure_text(self, error: Exception) -> str:
        import openai

        if isinstance(error, openai.AuthenticationError):
            reason = "the API key was rejected"
        elif isinstance(error, openai.RateLimitError):
            reason = "rate limit or quota reached"
        elif isinstance(error, openai.APIConnectionError):
            reason = "the API could not be reached"
        else:
            reason = type(error).__name__
        return f"The OpenAI call failed ({reason}); rule-based answers still work."
