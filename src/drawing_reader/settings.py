"""Settings: every `DRAWING_READER_*` variable in one place, read when it is used.

Values come from the environment. `load_env_file()` adds the lines of a `.env` file first, without
overriding anything already set, so the CLI, the app and Docker all see the same configuration.
Each setting is a function, not a module constant, so a value loaded after import still counts.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PREFIX = "DRAWING_READER_"
DEFAULT_CACHE = ".drawing_reader_cache"
DEFAULT_LOCAL_URL = "http://127.0.0.1:8080"
DEFAULT_FACT_BUDGET = 9000  # characters of facts for the local model: about 3k tokens
DEFAULT_MAX_LLM_CALLS = 40
TRUE_VALUES = ("1", "true", "yes", "on")

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def parse_env_text(text: str) -> dict[str, str]:
    """The KEY=value pairs of a .env file.

    Follows what Docker Compose and a POSIX shell accept: blank lines and `#` lines are skipped, an
    `export ` prefix is allowed, a value in single or double quotes is taken as written (a double-quoted
    value may hold `\\"` and `\\n`), and in an unquoted value a `#` after whitespace starts a comment.
    Lines that are not assignments are ignored."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _ENV_LINE.match(line)
        if not m or line.lstrip().startswith("#"):
            continue
        key, raw = m.group(1), m.group(2).strip()
        if raw[:1] in ("'", '"'):
            quote = raw[0]
            end = raw.find(quote, 1)
            while quote == '"' and end > 0 and raw[end - 1] == "\\":
                end = raw.find(quote, end + 1)
            value = raw[1:end] if end > 0 else raw[1:]
            if quote == '"':
                value = value.replace('\\"', '"').replace("\\n", "\n")
        else:
            value = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        out[key] = value
    return out


def load_env_file(path: str | Path = ".env") -> bool:
    """Add the variables of a .env file to the environment; ones already set win. False if no file."""
    p = Path(path)
    if not p.is_file():
        return False
    for key, value in parse_env_text(p.read_text(encoding="utf-8")).items():
        os.environ.setdefault(key, value)
    return True


def get(name: str, default: str = "") -> str:
    """`DRAWING_READER_<name>` from the environment, stripped; `default` when unset or empty."""
    return os.environ.get(PREFIX + name, "").strip() or default


def _int(name: str, default: int) -> int:
    value = get(name)
    try:
        return int(value) if value else default
    except ValueError:
        raise ValueError(f"{PREFIX}{name} must be a whole number, not {value!r}") from None


def cache_dir(default: str | Path = DEFAULT_CACHE) -> Path:
    """Where ingested documents, page images and cached answers are kept."""
    return Path(get("CACHE") or default)


def provider_name() -> str:
    """The provider to use when none is given: `DRAWING_READER_PROVIDER`, lower case; "" when unset."""
    return get("PROVIDER").lower()


def model_for(provider: str, default: str) -> str:
    """`DRAWING_READER_<PROVIDER>_MODEL`, else the provider's built-in default."""
    return get(f"{provider.upper()}_MODEL", default)


def local_url() -> str:
    return get("LOCAL_URL", DEFAULT_LOCAL_URL)


def local_model() -> str:
    """The model name to send to a local server; "" lets the server pick its loaded model."""
    return get("LOCAL_MODEL")


def local_fact_budget() -> int:
    return _int("LOCAL_FACT_BUDGET", DEFAULT_FACT_BUDGET)


def max_llm_calls() -> int:
    """Model calls (attempts) allowed per app session before answers fall back to rules only."""
    return _int("MAX_LLM_CALLS", DEFAULT_MAX_LLM_CALLS)


def anthropic_fallbacks() -> bool:
    return get("ANTHROPIC_FALLBACKS").lower() in TRUE_VALUES
