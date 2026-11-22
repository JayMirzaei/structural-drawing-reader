"""Choosing a provider by name or from the environment."""

from __future__ import annotations

import subprocess
import sys

import pytest

from drawing_reader.providers import PROVIDERS, create_provider, provider_names
from drawing_reader.providers.registry import PROVIDER_ENV, ProviderInfo


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for info in PROVIDERS.values():
        for name in info.key_env:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)


def test_names_start_with_none_and_cover_every_provider():
    assert provider_names() == ["none", "local", "gemini", "openai", "anthropic"]
    for info in PROVIDERS.values():
        assert info.load().name == info.name  # every entry points at a real class


def test_none_means_rules_only(tmp_path):
    assert create_provider("none", tmp_path) is None
    assert create_provider(cache_dir=tmp_path) is None  # nothing configured


def test_unknown_name_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="unknown provider 'nope'"):
        create_provider("nope", tmp_path)


def test_provider_is_read_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(PROVIDER_ENV, " OpenAI ")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = create_provider(cache_dir=tmp_path)
    assert p.name == "openai" and p.enabled and p.model == PROVIDERS["openai"].default_model()


@pytest.mark.parametrize("name", ["gemini", "openai", "anthropic"])
def test_a_missing_key_disables_the_provider_and_says_which_variable(tmp_path, name):
    p = create_provider(name, tmp_path)
    assert not p.enabled and PROVIDERS[name].key_env[0] in p.last_error
    with_key = create_provider(name, tmp_path, api_key="k", model="some-model")
    assert with_key.enabled and with_key.model == "some-model" and with_key.last_error is None


def test_a_missing_sdk_disables_the_provider_and_names_the_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(ProviderInfo, "sdk_installed", lambda self: False)
    p = create_provider("anthropic", tmp_path, api_key="k")
    assert not p.enabled and "'anthropic' extra" in p.last_error


def test_local_provider_takes_a_url_and_reports_an_unreachable_server(tmp_path):
    p = create_provider("local", tmp_path, base_url="http://127.0.0.1:9")  # the discard port: nothing listens
    assert p.name == "local" and not p.enabled and "not reachable at http://127.0.0.1:9" in p.last_error


def test_the_package_imports_without_any_optional_sdk():
    """SDKs are optional extras: they are imported inside the call path only. Checked in a fresh
    interpreter where importing any of them fails."""
    code = (
        "import sys\n"
        "for sdk in ('openai', 'anthropic', 'google.genai', 'rapidocr_onnxruntime'):\n"
        "    sys.modules[sdk] = None\n"
        "import drawing_reader\n"
        "from drawing_reader.providers import PROVIDERS, create_provider\n"
        "assert all(info.load() for info in PROVIDERS.values())\n"
        "assert not any(info.sdk_installed() for info in PROVIDERS.values() if info.sdk)\n"
        "assert create_provider('openai', '.', api_key='k').enabled is False\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
