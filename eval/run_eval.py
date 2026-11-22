"""Score the acceptance questions and print a table (the same as `drawing-reader eval`).

    uv run python eval/run_eval.py                              # eval/questions.yaml, rules only
    uv run python eval/run_eval.py eval/questions_scan.yaml     # the scanned sheet (needs the `ocr` extra)
    uv run python eval/run_eval.py --provider anthropic         # questions the rules miss go to an LLM

Rules-only runs are deterministic. See `drawing_reader.evaluation` for the questions-file format.
"""

from __future__ import annotations

import sys

from drawing_reader.cli import main

if __name__ == "__main__":
    sys.exit(main(["eval", *sys.argv[1:]]))
