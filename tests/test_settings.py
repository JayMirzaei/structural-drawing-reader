"""Settings: the .env parser, and settings read when used rather than frozen at import."""

from __future__ import annotations

from pathlib import Path

import pytest

from drawing_reader import settings
from drawing_reader.providers import create_provider

ROOT = Path(__file__).resolve().parents[1]


def test_env_text_handles_comments_quotes_and_export():
    text = "\n".join(
        [
            "# a comment line",
            "",
            "PLAIN=value",
            "SPACED = spaced value  # an inline comment",
            "HASH_IN_VALUE=abc#def",
            'DOUBLE="quoted # not a comment"  # but this is',
            "SINGLE='it''s'",
            'ESCAPED="say \\"hi\\""',
            "export EXPORTED=1",
            "EMPTY=",
            "not an assignment",
        ]
    )
    assert settings.parse_env_text(text) == {
        "PLAIN": "value",
        "SPACED": "spaced value",
        "HASH_IN_VALUE": "abc#def",
        "DOUBLE": "quoted # not a comment",
        "SINGLE": "it",
        "ESCAPED": 'say "hi"',
        "EXPORTED": "1",
        "EMPTY": "",
    }


def test_the_example_env_file_sets_nothing_unexpected():
    """Every line of .env.example parses to an empty value: no commented default leaks into a setting."""
    values = settings.parse_env_text((ROOT / ".env.example").read_text())
    assert values == {
        "DRAWING_READER_PROVIDER": "",
        "GEMINI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
    }


def test_an_env_file_never_overrides_the_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DRAWING_READER_LOCAL_URL=http://from-file:1\nDRAWING_READER_MAX_LLM_CALLS=7  # per session\n")
    monkeypatch.setenv("DRAWING_READER_LOCAL_URL", "http://from-env:2")
    monkeypatch.delenv("DRAWING_READER_MAX_LLM_CALLS", raising=False)
    assert settings.load_env_file(env) and not settings.load_env_file(tmp_path / "absent.env")
    assert settings.local_url() == "http://from-env:2"
    assert settings.max_llm_calls() == 7


def test_settings_are_read_when_used(monkeypatch):
    """A value set after the package was imported still counts (the app loads .env after Python starts)."""
    monkeypatch.setenv("DRAWING_READER_LOCAL_FACT_BUDGET", "1234")
    monkeypatch.setenv("DRAWING_READER_OPENAI_MODEL", "model-from-env")
    monkeypatch.setenv("DRAWING_READER_CACHE", "/tmp/somewhere")
    assert settings.local_fact_budget() == 1234
    assert settings.cache_dir() == Path("/tmp/somewhere")
    provider = create_provider("openai", ".", api_key="sk-test")
    assert provider.model == "model-from-env"


def test_a_bad_number_names_the_setting(monkeypatch):
    monkeypatch.setenv("DRAWING_READER_MAX_LLM_CALLS", "forty")
    with pytest.raises(ValueError, match="DRAWING_READER_MAX_LLM_CALLS"):
        settings.max_llm_calls()


def test_the_provider_setting_picks_the_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("DRAWING_READER_PROVIDER", " Local ")
    monkeypatch.setenv("DRAWING_READER_LOCAL_URL", "http://127.0.0.1:9")
    provider = create_provider(cache_dir=tmp_path)
    assert provider.name == "local" and provider.base_url == "http://127.0.0.1:9"
