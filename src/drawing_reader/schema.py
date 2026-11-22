"""The fact index: everything the app knows about a drawing set, with evidence locations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

FactKind = Literal[
    "sheet",
    "titleblock",
    "revision",
    "note",
    "material",
    "label",
    "dimension",
    "angle",
    "elevation",
    "grid",
    "callout",
    "view",
    "reference",
    "text",
    "weld",
]

# Fact attributes worth showing a model next to the value (the rest are layout detail).
PROMPT_ATTRS = (
    "orientation",
    "family",
    "section",
    "heading",
    "number",
    "detail",
    "target_sheet",
    "name",
    "scale",
    "title",
)


class Fact(BaseModel):
    id: str
    kind: FactKind
    value: str
    unit: str | None = None
    sheet: str  # sheet number as printed, e.g. "S.2"; falls back to "P3"
    page: int  # 1-based page index
    view: str | None = None  # view title the fact sits in, if known
    bbox: tuple[float, float, float, float]
    source_text: str
    method: str = "rule"
    confidence: float = 0.8
    attrs: dict[str, Any] = Field(default_factory=dict)  # kind-specific extras
    links: list[str] = Field(default_factory=list)

    def short(self) -> str:
        v = self.value if len(self.value) < 90 else self.value[:87] + "..."
        return f"[{self.id}] {self.kind} @ {self.sheet}: {v}"


class SheetMeta(BaseModel):
    page: int
    number: str
    title: str = ""
    scale: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    image_path: str = ""
    image_scale: float = 1.0
    width: float = 0
    height: float = 0
    text: str = ""


class Index(BaseModel):
    doc_id: str
    source: str
    is_vector: bool
    from_ocr: bool = False  # True when text came from OCR of scanned pages
    project: dict[str, str] = Field(default_factory=dict)
    sheets: list[SheetMeta] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)

    # ---- convenience -------------------------------------------------------------------------
    def by_kind(self, *kinds: str) -> list[Fact]:
        return [f for f in self.facts if f.kind in kinds]

    def get(self, fid: str) -> Fact | None:
        return next((f for f in self.facts if f.id == fid), None)

    def sheet_numbers(self) -> list[str]:
        return [s.number for s in self.sheets]

    def sheet_by_number(self, number: str) -> SheetMeta | None:
        return next((s for s in self.sheets if s.number == number), None)

    def compact_json(self) -> str:
        """Compact representation for LLM prompts: one line per fact."""
        rows = []
        for f in self.facts:
            row = {"id": f.id, "k": f.kind, "v": f.value, "sheet": f.sheet}
            if f.unit:
                row["u"] = f.unit
            if f.view:
                row["view"] = f.view
            extras = {k: v for k, v in f.attrs.items() if k in PROMPT_ATTRS}
            if extras:
                row["a"] = extras
            rows.append(json.dumps(row, ensure_ascii=False))
        return "\n".join(rows)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Index:
        return cls.model_validate_json(Path(path).read_text())
