"""Google Gemini provider (the `gemini` extra)."""

from __future__ import annotations

from pathlib import Path

from drawing_reader import settings
from drawing_reader.providers.base import SYSTEM_PROMPT, BaseProvider, LLMAnswer, full_prompt
from drawing_reader.schema import Index

DEFAULT_MODEL = "gemini-3.8-flash"  # DRAWING_READER_GEMINI_MODEL overrides it


class GeminiProvider(BaseProvider):
    """Sends the whole fact index, the picked sheets' text and their images; the reply is constrained
    to the `LLMAnswer` schema by the API."""

    name = "gemini"
    cache_subdir = "llm"

    def __init__(self, cache_dir: str | Path, model: str | None = None, api_key: str | None = None):
        super().__init__(cache_dir, model or settings.model_for(self.name, DEFAULT_MODEL), api_key)
        self.enabled = bool(api_key)  # the registry reads the key from the environment
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _complete(self, question: str, idx: Index, sheets: list[str], hint_ids: list[str] | None) -> str:
        from google.genai import types

        prompt = full_prompt(question, idx, sheets, hint_ids)
        parts = [types.Part.from_text(text=f"{prompt.index_text}\n\n{prompt.context_text}")]
        for image in prompt.images:
            parts.append(types.Part.from_text(text=f"Image of sheet {image.sheet}:"))
            parts.append(types.Part.from_bytes(data=image.jpeg, mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=prompt.question_text))
        response = self._get_client().models.generate_content(
            model=self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=LLMAnswer,
                temperature=0.2,
            ),
        )
        return response.text or "{}"

    def failure_text(self, error: Exception) -> str:
        return (
            f"The LLM call failed ({type(error).__name__}). If this is a 429, the quota is exhausted for now; "
            "rule-based answers still work."
        )
