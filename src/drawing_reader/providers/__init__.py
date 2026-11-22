"""LLM providers: the optional fallback for questions the rules cannot answer with confidence.

All providers share one contract (`base.py`): the same system prompt, the same JSON answer shape, and
the same validation of what comes back. `registry.create_provider` picks one by name; "none" means the
reader runs on rules alone.
"""

from drawing_reader.providers.base import (
    SYSTEM_PROMPT,
    AnswerCache,
    BaseProvider,
    LLMAnswer,
    Provider,
    ProviderError,
    pick_sheets,
    strict_json_schema,
    to_answer,
    unsupported_numbers,
)
from drawing_reader.providers.registry import PROVIDERS, ProviderInfo, create_provider, provider_names

__all__ = [
    "PROVIDERS",
    "SYSTEM_PROMPT",
    "AnswerCache",
    "BaseProvider",
    "LLMAnswer",
    "Provider",
    "ProviderError",
    "ProviderInfo",
    "create_provider",
    "pick_sheets",
    "provider_names",
    "strict_json_schema",
    "to_answer",
    "unsupported_numbers",
]
