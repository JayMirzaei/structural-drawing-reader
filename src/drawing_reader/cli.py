"""Command-line entry point: `drawing-reader index|summary|ask|eval`.

    drawing-reader index set.pdf [--out index.json]
    drawing-reader summary set.pdf
    drawing-reader ask set.pdf "What size are the columns?" [--provider NAME] [--evidence out.png] [--json]
    drawing-reader eval [questions.yaml ...] [--provider NAME]

Every command reads the PDF through the same kind of cache as the app (`--cache`, default the
DRAWING_READER_CACHE environment variable, else `.drawing_reader_cache` in the current folder), so a
second run on the same file skips extraction. Without `--provider` (or DRAWING_READER_PROVIDER) the
answers come from the rules alone and nothing leaves the machine. The CLI reads settings from the
environment only, not from a .env file, so a run is reproducible from its command line.

Exit status: 0 on success, 1 when `eval` has an unexpected failure, 2 for a file that cannot be read.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from drawing_reader import __version__, settings
from drawing_reader.evaluation import format_table, load_questions, run_questions, score
from drawing_reader.ingest import UnreadablePDF, ingest
from drawing_reader.parse import build_index
from drawing_reader.providers import create_provider, provider_names
from drawing_reader.qa import Answer, answer, first_look, render_sheet, scope_advice
from drawing_reader.schema import Index

DEFAULT_QUESTIONS = Path("eval") / "questions.yaml"  # relative to the current folder: run from the repository


class CLIError(Exception):
    """A problem with the input that is reported in one line, with exit status 2 (no traceback)."""


def default_cache() -> Path:
    return settings.cache_dir()


def load_index(pdf: Path, cache: Path) -> Index:
    if not pdf.is_file():
        raise CLIError(f"no such file: {pdf}")
    try:
        return build_index(ingest(pdf, cache))
    except UnreadablePDF as error:
        raise CLIError(f"cannot read {pdf}: {error}") from None


def plain_text(markdown: str) -> str:
    """The first-look Markdown for a terminal: bold markers removed."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", markdown)


def make_provider(name: str | None, cache: Path, idx: Index):
    """The LLM provider for this run, or None for rules only. An unusable provider (no key, no SDK, server
    down) is reported on stderr and the run continues on the rules alone."""
    llm = create_provider(name, cache / idx.doc_id)
    if llm is not None and not llm.enabled:
        print(f"provider {llm.name!r} is not available ({llm.last_error}); using the rules only.", file=sys.stderr)
        return None
    return llm


# ---- commands --------------------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> int:
    idx = load_index(args.pdf, args.cache)
    data = idx.model_dump_json(indent=1)
    if args.out:
        args.out.write_text(data)
        print(f"wrote {args.out}: {len(idx.sheets)} sheet(s), {len(idx.facts)} fact(s)", file=sys.stderr)
    else:
        print(data)
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    idx = load_index(args.pdf, args.cache)
    print(first_look(idx) if args.markdown else plain_text(first_look(idx)))
    for notice in scope_advice(idx):
        print(f"\nNote: {notice}")
    return 0


def evidence_images(idx: Index, ans: Answer, out: Path) -> list[Path]:
    """Draw a box round every cited fact on its sheet. Evidence on one sheet is written to `out`; on
    several sheets, one file per sheet next to it, named `<stem>_<sheet><suffix>`. Returns the files."""
    written = []
    for sheet in ans.sheets:
        path = out if len(ans.sheets) == 1 else out.with_name(f"{out.stem}_{sheet}{out.suffix}")
        cited = [fid for fid in ans.fact_ids if (f := idx.get(fid)) and f.sheet == sheet]
        img = render_sheet(idx, sheet, set(), cited)
        if img is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(path)
            written.append(path)
    return written


def cmd_ask(args: argparse.Namespace) -> int:
    idx = load_index(args.pdf, args.cache)
    ans = answer(args.question, idx, llm=make_provider(args.provider, args.cache, idx))
    cited = [f for fid in ans.fact_ids if (f := idx.get(fid))]
    images = evidence_images(idx, ans, args.evidence) if args.evidence else []
    if args.json:
        result = {
            "question": args.question,
            "answer": ans.text,
            "method": ans.method,
            "confidence": round(ans.confidence, 2),
            "sheets": ans.sheets,
            "caveats": ans.caveats,
            "facts": [f.model_dump(mode="json") for f in cited],
            "evidence_images": [str(p) for p in images],
        }
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0
    print(ans.text)
    print(f"\n[{ans.method}, confidence {ans.confidence:.2f}]")
    for caveat in ans.caveats:
        print(f"Caveat: {caveat}")
    if cited:
        print("\nEvidence:")
        for f in cited:
            print(f"- {f.short()}  (page {f.page}, box {tuple(round(v) for v in f.bbox)})")
    for path in images:
        print(f"Evidence image: {path}")
    if args.evidence and not images:
        print("No evidence image: the answer cites no fact.", file=sys.stderr)
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Exit status 1 when a question not marked as a known limit fails, 2 on a bad questions file."""
    failed = False
    for path in args.questions or [DEFAULT_QUESTIONS]:
        try:
            question_set = load_questions(path)
        except (OSError, ValueError) as error:
            print(f"drawing-reader eval: {error}", file=sys.stderr)
            return 2
        idx = load_index(question_set.pdf, args.cache)
        llm = make_provider(args.provider, args.cache, idx)
        results = run_questions(question_set, idx, llm)
        print(f"== {path} ({question_set.pdf.name}, {'rules + ' + llm.name if llm else 'rules only'})")
        print(format_table(results, details=not args.quiet, timing=args.timing))
        if llm is not None:
            print(f"LLM calls: {llm.calls}")
        print()
        failed |= score(results)["FAIL"] > 0
    return 1 if failed else 0


# ---- argument parsing ------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drawing-reader", description="Read structural drawing PDFs.")
    parser.add_argument("--version", action="version", version=f"drawing-reader {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--cache", type=Path, default=None, help="cache folder (default: .drawing_reader_cache)")
    llm = argparse.ArgumentParser(add_help=False)
    llm.add_argument("--provider", choices=provider_names(), default=None, help="LLM for questions the rules miss")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("index", parents=[common], help="print (or write) the fact index as JSON")
    p.add_argument("pdf", type=Path)
    p.add_argument("--out", type=Path, help="write the JSON to this file instead of printing it")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("summary", parents=[common], help="what was read: sheets, members, materials, gaps")
    p.add_argument("pdf", type=Path)
    p.add_argument("--markdown", action="store_true", help="print the summary as Markdown (as the app shows it)")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("ask", parents=[common, llm], help="answer a question and show its evidence")
    p.add_argument("pdf", type=Path)
    p.add_argument("question")
    p.add_argument("--evidence", type=Path, help="write the sheet image with the cited facts boxed (PNG)")
    p.add_argument("--json", action="store_true", help="print the answer and the cited facts as JSON")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("eval", parents=[common, llm], help="score the acceptance questions")
    p.add_argument("questions", type=Path, nargs="*", help=f"questions files (default: {DEFAULT_QUESTIONS})")
    p.add_argument("--quiet", action="store_true", help="the table only, no failure details")
    p.add_argument("--timing", action="store_true", help="add the time each question took")
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.cache = args.cache or default_cache()
    try:
        return args.func(args)
    except CLIError as error:
        print(f"drawing-reader: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
