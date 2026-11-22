"""Showing answers as Markdown without letting drawing text become markup.

Answers and the first look are built from our own scaffolding (a bold label, a list bullet) around
text copied from the drawing or written by a model. Drawing text is untrusted: a note could hold
`![x](https://...)`, which a Markdown renderer would turn into an image the browser fetches. So
everything except the scaffolding is escaped before it reaches a Markdown renderer.
"""

from __future__ import annotations

import re

_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+!|~$])")
_LINE = re.compile(r"^(?P<bullet>\s*(?:[-*]|\d{1,3}\.)\s+)?(?:\*\*(?P<bold>[^*\n]+?)\*\*)?(?P<rest>.*)$")


def escape_markdown(text: str) -> str:
    """`text` with every character that Markdown (or the HTML inside it) would interpret backslash-escaped,
    so it renders exactly as written: no links, images, emphasis, headings or tags."""
    return _SPECIAL.sub(r"\\\1", text)


def safe_markdown(text: str) -> str:
    """Our answer Markdown with only its scaffolding kept: per line, a leading list bullet and a leading
    `**bold**` label stay Markdown; everything else, including the text inside the bold label, is escaped."""
    out = []
    for line in text.split("\n"):
        m = _LINE.match(line)
        bullet, bold, rest = m.group("bullet") or "", m.group("bold"), m.group("rest")
        head = f"**{escape_markdown(bold)}**" if bold else ""
        out.append(bullet + head + escape_markdown(rest))
    return "\n".join(out)
