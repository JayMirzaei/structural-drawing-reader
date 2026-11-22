"""Read structural drawing PDFs into a typed, cited fact index and answer questions from it.

The pipeline has three steps, each usable on its own:

    doc = ingest("set.pdf", cache_dir)   # PDF pages -> text runs, line geometry, page images
    idx = build_index(doc)               # rule parsers -> Index of Fact objects with evidence boxes
    ans = answer("What are the column sections?", idx)   # rules first, optional LLM fallback
"""

from drawing_reader.ingest import ingest
from drawing_reader.parse import build_index
from drawing_reader.qa import Answer, answer
from drawing_reader.schema import Fact, Index, SheetMeta

__version__ = "1.0.0"

__all__ = ["Answer", "Fact", "Index", "SheetMeta", "__version__", "answer", "build_index", "ingest"]
