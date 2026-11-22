"""Rule-based parsers: primitives in, facts out.

Every rule states the drafting convention it assumes. Rules are geometric and generic (no
sheet-specific coordinates), so any drawing set is parsed the same way. The modules at this level
hold the vocabulary and text helpers by topic; `sheet/` holds the per-sheet parser, split into one
rule group per module; `index.py` assembles the set-level index.
"""

from drawing_reader.parse.index import build_index
from drawing_reader.parse.sheet import SheetParser

__all__ = ["SheetParser", "build_index"]
