"""Pick a provider by name, from configuration or the environment.

    provider = create_provider("anthropic", cache_dir)     # or None for rules only
    provider = create_provider(cache_dir=cache_dir)        # reads DRAWING_READER_PROVIDER

Provider modules import their SDK only when a call is made, so listing and constructing providers
works without any optional dependency installed.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path

from drawing_reader import settings
from drawing_reader.providers.base import BaseProvider

PROVIDER_ENV = "DRAWING_READER_PROVIDER"
NONE = "none"


@dataclass(frozen=True)
class ProviderInfo:
    """What a caller (CLI, UI) needs to know to offer a provider."""

    name: str
    title: str
    module: str  # where the class lives
    cls: str
    key_env: tuple[str, ...] = ()  # environment variables an API key is read from; empty = no key needed
    sdk: str = ""  # import name of the optional SDK; empty = none needed
    extra: str = ""  # the pyproject extra that installs it

    @property
    def needs_key(self) -> bool:
        return bool(self.key_env)

    def sdk_installed(self) -> bool:
        return not self.sdk or importlib.util.find_spec(self.sdk) is not None

    def load(self) -> type[BaseProvider]:
        return getattr(importlib.import_module(self.module), self.cls)

    def default_model(self) -> str:
        """The model used when none is given: DRAWING_READER_<NAME>_MODEL, else the built-in default."""
        return settings.model_for(self.name, getattr(importlib.import_module(self.module), "DEFAULT_MODEL", ""))

    def key_from_env(self) -> str:
        return next((os.environ[v] for v in self.key_env if os.environ.get(v)), "")


_P = "drawing_reader.providers."
PROVIDERS: dict[str, ProviderInfo] = {
    info.name: info
    for info in (
        ProviderInfo("local", "Local model (OpenAI-compatible server)", _P + "local", "LocalProvider"),
        ProviderInfo(
            "gemini",
            "Google Gemini",
            _P + "gemini",
            "GeminiProvider",
            ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "google.genai",
            "gemini",
        ),
        ProviderInfo("openai", "OpenAI", _P + "openai", "OpenAIProvider", ("OPENAI_API_KEY",), "openai", "openai"),
        ProviderInfo(
            "anthropic",
            "Anthropic Claude",
            _P + "anthropic",
            "AnthropicProvider",
            ("ANTHROPIC_API_KEY",),
            "anthropic",
            "anthropic",
        ),
    )
}


def provider_names() -> list[str]:
    """Every accepted provider name, "none" (rules only) first."""
    return [NONE, *PROVIDERS]


def create_provider(
    name: str | None = None,
    cache_dir: str | Path = ".",
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> BaseProvider | None:
    """The provider called `name`, or None for "none" (answers come from the rules alone).

    `name` defaults to the DRAWING_READER_PROVIDER environment variable, then "none". `cache_dir` is
    where answers for one document are kept. `api_key` overrides the provider's environment variable;
    `base_url` applies to the local provider only. A provider that cannot be used right now (no key,
    server not running) is still returned, with `enabled` False and the reason in `last_error`.
    """
    name = (name or settings.provider_name() or NONE).strip().lower()
    if name == NONE:
        return None
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose one of: {', '.join(provider_names())}")
    info = PROVIDERS[name]
    cls = info.load()
    if name == "local":
        return cls(cache_dir, base_url=base_url, model=model)
    provider = cls(cache_dir, model=model, api_key=api_key or info.key_from_env() or None)
    if not info.sdk_installed():
        provider.enabled = False
        provider.last_error = f"the {info.sdk} package is not installed (install the '{info.extra}' extra)"
    elif not provider.enabled:
        provider.last_error = f"no API key: set {' or '.join(info.key_env)}"
    return provider
