"""Build the static demo site from the synthetic examples: no server, no key, no JavaScript.

Usage::

    uv sync --extra ocr                      # without it the scanned example is left out
    uv run python scripts/build_site.py      # writes site/ (git-ignored)
    python -m http.server -d site            # look at it locally

For each acceptance-questions file (default: every ``eval/questions*.yaml``) the site gets a page with
the first-look summary and the sheets as read, and a page with every question, its rule answer, the
facts the answer cites and the sheet images with those facts boxed. Everything is computed here, ahead
of time, by the same code the app and the command line use, on rules alone. The output depends only
on the repository's files, so two builds are byte-identical.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

from drawing_reader import __version__, ocr
from drawing_reader.evaluation import QuestionSet, Result, load_questions, run_questions, score
from drawing_reader.ingest import ingest
from drawing_reader.parse import build_index
from drawing_reader.qa import first_look, render_sheet
from drawing_reader.schema import Fact, Index

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/JayMirzaei/structural-drawing-reader"
COMPANION_URL = "https://github.com/JayMirzaei/steel-drawing-ontology"
IMAGE_WIDTH = 1400  # pixels; sheets are rendered larger, this is enough to read the boxed text
OVERLAY_KINDS = {"label", "elevation", "callout", "grid"}  # the app's default overlay
OPEN_FACTS = 8  # a longer list of cited facts is folded away

CSS = """
:root { --bg: #fbfbfa; --fg: #1d1d1f; --muted: #5f6368; --line: #dcdcdc; --card: #ffffff;
        --accent: #b42318; --pass: #1a7f37; --limit: #9a6700; --code: #f2f2f0; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161618; --fg: #e8e8e8; --muted: #a0a0a8; --line: #34343a; --card: #1f1f23;
          --accent: #ff7b72; --pass: #3fb950; --limit: #d29922; --code: #2a2a30; }
  img.sheet { filter: none; background: #fff; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header, main, footer { max-width: 1100px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 24px; border-bottom: 1px solid var(--line); }
header a.home { color: var(--fg); text-decoration: none; font-weight: 600; }
nav { display: flex; flex-wrap: wrap; gap: 4px 18px; padding: 8px 0 14px; font-size: 15px; }
a { color: var(--accent); }
h1 { font-size: 28px; line-height: 1.25; margin: 28px 0 8px; }
h2 { font-size: 21px; margin: 36px 0 10px; }
h3 { font-size: 17px; margin: 0 0 6px; }
p.lead { font-size: 18px; color: var(--muted); max-width: 760px; }
.muted { color: var(--muted); }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: 0.92em; }
pre { background: var(--code); padding: 12px; border-radius: 6px; overflow-x: auto; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px 18px;
        margin: 14px 0; }
.badge { display: inline-block; font-size: 13px; font-weight: 600; padding: 1px 8px; border-radius: 10px;
         border: 1px solid currentColor; margin-right: 8px; }
.badge.pass { color: var(--pass); } .badge.limit { color: var(--limit); } .badge.fail { color: var(--accent); }
.meta { font-size: 14px; color: var(--muted); margin: 6px 0; }
.answer { margin: 8px 0; }
.answer ul { margin: 4px 0; padding-left: 22px; }
.caveat { font-size: 14px; color: var(--muted); margin: 2px 0; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; margin: 8px 0; display: block;
        overflow-x: auto; }
th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 4px 8px; vertical-align: top; }
td code, td.nowrap { white-space: nowrap; }
details summary { cursor: pointer; font-size: 14px; color: var(--muted); margin: 6px 0; }
ol.toc { columns: 2 300px; font-size: 15px; padding-left: 22px; }
img.sheet { width: 100%; height: auto; border: 1px solid var(--line); border-radius: 4px; background: #fff; }
figure { margin: 12px 0; }
figcaption { font-size: 14px; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
.score { font-size: 20px; font-weight: 600; }
footer { border-top: 1px solid var(--line); margin-top: 48px; padding-top: 14px; padding-bottom: 32px;
         font-size: 14px; color: var(--muted); }
"""


@dataclass
class SetReport:
    """One example set as read: its index and the answers to its questions."""

    slug: str
    title: str
    questions_file: Path
    question_set: QuestionSet
    idx: Index
    results: list[Result]


# ---- small HTML helpers ------------------------------------------------------------------------


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def markdown(text: str) -> str:
    """The small Markdown subset the reader writes (bold, `- ` lists, paragraphs) as HTML."""
    out: list[str] = []
    in_list = False
    for raw in text.splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(raw.rstrip()))
        if line.lstrip().startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{line.lstrip()[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def page(title: str, body: str, depth: int, sets: list[SetReport]) -> str:
    """A complete HTML page. `depth` is how many folders below the site root the page sits."""
    up = "../" * depth
    links = [f'<a href="{up}index.html">Overview</a>']
    for s in sets:
        links.append(f'<a href="{up}{s.slug}/index.html">{esc(s.title)}</a>')
        links.append(f'<a href="{up}{s.slug}/questions.html">{esc(s.title)}: questions</a>')
    links.append(f'<a href="{REPO_URL}">Source</a>')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header><a class="home" href="{up}index.html">structural-drawing-reader</a>
<nav>{" ".join(links)}</nav></header>
<main>
{body}
</main>
<footer>Built from the synthetic examples by <code>scripts/build_site.py</code>, drawing-reader {__version__}.
Answers are computed ahead of time by the rules alone; no model and no server are involved.
The drawings are invented. MIT licence, Jay Mirzaei.</footer>
</body>
</html>
"""


def save_image(img: Image.Image, path: Path) -> None:
    """Scale to IMAGE_WIDTH and store on a small palette: line drawings stay sharp at a fraction of the size."""
    if img.width > IMAGE_WIDTH:
        img = img.resize((IMAGE_WIDTH, round(img.height * IMAGE_WIDTH / img.width)), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def folded(summary: str, content: str) -> str:
    return f"<details><summary>{esc(summary)}</summary>{content}</details>"


def fact_table(facts: list[Fact]) -> str:
    rows = "".join(
        "<tr>"
        f"<td><code>{esc(f.id)}</code></td><td>{esc(f.kind)}</td><td>{esc(f.value)}</td>"
        f'<td>{esc(f.sheet)}</td><td>{f.page}</td><td class="nowrap">{esc(", ".join(str(round(v)) for v in f.bbox))}</td>'
        f"<td>{f.confidence:.2f}</td><td>{esc(f.source_text[:120])}</td>"
        "</tr>"
        for f in facts
    )
    return (
        "<table><thead><tr><th>fact id</th><th>kind</th><th>value</th><th>sheet</th><th>page</th>"
        "<th>box (pt)</th><th>conf</th><th>source text</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


# ---- reading the examples ----------------------------------------------------------------------


def read_set(questions_file: Path, cache: Path) -> SetReport:
    question_set = load_questions(questions_file)
    idx = build_index(ingest(question_set.pdf, cache))
    stem = question_set.pdf.stem
    title = stem.replace("_", " ").capitalize()
    return SetReport(stem.replace("_", "-"), title, questions_file, question_set, idx, run_questions(question_set, idx))


def needs_ocr(questions_file: Path) -> bool:
    """True when the set is a scan (no text layer), which only the OCR extra can read."""
    with pymupdf.open(load_questions(questions_file).pdf) as doc:
        return not any(p.get_text().strip() for p in doc)


# ---- pages -------------------------------------------------------------------------------------


def status_badge(result: Result) -> str:
    status = result.status
    css = {"pass": "pass", "fixed": "pass", "limit": "limit"}.get(status, "fail")
    label = {"limit": "known limit", "fixed": "known limit, now passing", "FAIL": "fail"}.get(status, status)
    return f'<span class="badge {css}">{esc(label)}</span>'


def score_line(results: list[Result]) -> str:
    s = score(results)
    line = f"{s['passed']} of {s['scored']} scored questions pass"
    if s["limit"] + s["fixed"]:
        line += f"; {s['limit'] + s['fixed']} more are known limits ({s['limit']} still failing)"
    return line


def set_page(report: SetReport, out: Path, sets: list[SetReport]) -> None:
    idx = report.idx
    folder = out / report.slug
    kinds_per_sheet = {s.number: Counter(f.kind for f in idx.facts if f.sheet == s.number) for s in idx.sheets}
    cards = []
    for meta in idx.sheets:
        image = render_sheet(idx, meta.number, OVERLAY_KINDS, [])
        name = f"sheets/{meta.number}.png"
        if image is not None:
            save_image(image, folder / name)
        counts = ", ".join(f"{n} {k}" for k, n in sorted(kinds_per_sheet[meta.number].items()))
        cards.append(
            f'<div class="card"><h3>{esc(meta.number)}: {esc(meta.title)}</h3>'
            f'<p class="meta">scale {esc(meta.scale or "not found")} · facts: {esc(counts)}</p>'
            f'<figure><img class="sheet" src="{name}" alt="Sheet {esc(meta.number)} with the facts read from it '
            f'outlined" loading="lazy"><figcaption>Thin boxes: member labels (red), level markers, callouts, '
            f"grid bubbles, as read.</figcaption></figure></div>"
        )
    source = "a scan, read by OCR" if idx.from_ocr else "a vector PDF, read directly"
    body = f"""<h1>{esc(report.title)}</h1>
<p class="lead">{len(idx.sheets)} sheet(s), {source}. {len(idx.facts)} facts in the index.
<a href="questions.html">{esc(score_line(report.results))}</a>.</p>
<h2>First look</h2>
<div class="card">{markdown(first_look(idx))}</div>
<h2>Sheets as read</h2>
{"".join(cards)}"""
    (folder / "index.html").write_text(page(report.title, body, 1, sets))


def questions_page(report: SetReport, out: Path, sets: list[SetReport]) -> None:
    idx = report.idx
    folder = out / report.slug
    cards: list[str] = []
    toc: list[str] = []
    for result in report.results:
        question, ans = result.question, result.answer
        cited = [f for fid in ans.fact_ids if (f := idx.get(fid))]
        figures = []
        for sheet in ans.sheets:
            ids = [f.id for f in cited if f.sheet == sheet]
            image = render_sheet(idx, sheet, set(), ids)
            if image is None:
                continue
            name = f"evidence/{question.id}_{sheet}.png"
            save_image(image, folder / name)
            figures.append(
                f'<figure><img class="sheet" src="{name}" alt="Sheet {esc(sheet)} with the cited facts boxed in red" '
                f'loading="lazy"><figcaption>{esc(sheet)}: {len(ids)} cited fact(s) boxed in red.</figcaption></figure>'
            )
        caveats = "".join(f'<p class="caveat">Caveat: {esc(c)}</p>' for c in ans.caveats)
        limit = f'<p class="meta">Known limit: {esc(question.known_limit)}</p>' if question.known_limit else ""
        problems = f'<p class="meta">Check: {esc("; ".join(result.problems))}</p>' if result.problems else ""
        expected = ", ".join(question.expect)
        cards.append(
            f'<div class="card" id="{esc(question.id)}"><h3>{status_badge(result)}{esc(question.q)}</h3>'
            f'<div class="answer">{markdown(ans.text)}</div>'
            f'<p class="meta">answered by <code>{esc(ans.method)}</code> · confidence {ans.confidence:.2f}'
            f" · expected to contain: {esc(expected)}</p>{limit}{problems}{caveats}"
            + (fact_table(cited) if 0 < len(cited) <= OPEN_FACTS else "")
            + (folded(f"{len(cited)} cited facts", fact_table(cited)) if len(cited) > OPEN_FACTS else "")
            + ("" if cited else '<p class="meta">No fact cited.</p>')
            + (f'<div class="grid">{"".join(figures)}</div>' if figures else "")
            + "</div>"
        )
        toc.append(f'<li><a href="#{esc(question.id)}">{esc(question.q)}</a> {status_badge(result)}</li>')
    source = report.questions_file
    shown = source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else source.name
    body = f"""<h1>{esc(report.title)}: questions</h1>
<p class="lead">The acceptance questions in <code>{esc(shown)}</code>, answered by the
rules alone. <span class="score">{esc(score_line(report.results))}.</span> A known limit is a question the
reader gets wrong today; it stays in the file with the reason, and it is shown here as it is answered.</p>
<ol class="toc">{"".join(toc)}</ol>
{"".join(cards)}"""
    (folder / "questions.html").write_text(page(f"{report.title}: questions", body, 1, sets))


def landing_page(out: Path, sets: list[SetReport], skipped: list[Path]) -> None:
    rows = "".join(
        f'<div class="card"><h3><a href="{s.slug}/index.html">{esc(s.title)}</a></h3>'
        f'<p class="meta">{len(s.idx.sheets)} sheet(s), {"scan (OCR)" if s.idx.from_ocr else "vector"}, '
        f"{len(s.idx.facts)} facts</p>"
        f'<p><a href="{s.slug}/questions.html">{esc(score_line(s.results))}</a></p></div>'
        for s in sets
    )
    note = (
        f'<p class="muted">Not built here: {esc(", ".join(p.name for p in skipped))} (a scan; needs the '
        "<code>ocr</code> extra).</p>"
        if skipped
        else ""
    )
    body = f"""<h1>A rules-first reader for structural drawing PDFs</h1>
<p class="lead">It reads a drawing set into a typed index of facts (sheet, box, source text, confidence),
answers questions from that index with deterministic rules, and shows the evidence on the sheet. A language
model is asked only when no rule is confident, and it may cite only facts that exist.</p>
<p>This page is a static demo built from the synthetic example drawings in the repository: every answer
below was computed ahead of time by the rules alone. The interactive app, the command line and the
optional model providers run locally; see the <a href="{REPO_URL}#readme">README</a>.</p>
<h2>Example sets</h2>
<div class="grid">{rows}</div>
{note}
<h2>How a question is answered</h2>
<pre>PDF -> text runs, lines, circles (or OCR for a scan) -> per-sheet rule parsers -> fact index
question -> router -> rule answerers -> best answer (+ optional model when no rule is sure)
answer -> cited fact ids -> boxes drawn on the sheet image</pre>
<p>The later work, a vocabulary and validated knowledge graph for steel fabrication drawings that grew out
of this reader, is <a href="{COMPANION_URL}">steel-drawing-ontology</a>.</p>"""
    (out / "index.html").write_text(page("structural-drawing-reader: demo", body, 0, sets))


def build(out: Path, questions_files: list[Path], cache: Path) -> list[SetReport]:
    """Build the whole site into `out` (replaced if it exists). Returns what was read."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    sets: list[SetReport] = []
    skipped: list[Path] = []
    for path in questions_files:
        if needs_ocr(path) and not ocr.available():
            skipped.append(path)
            continue
        sets.append(read_set(path, cache))
    for report in sets:
        set_page(report, out, sets)
        questions_page(report, out, sets)
    landing_page(out, sets, skipped)
    (out / "style.css").write_text(CSS.lstrip())
    (out / ".nojekyll").write_text("")
    return sets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "site", help="output folder (default: site/)")
    parser.add_argument("questions", type=Path, nargs="*", help="questions files (default: eval/questions*.yaml)")
    args = parser.parse_args(argv)
    files = args.questions or sorted((ROOT / "eval").glob("questions*.yaml"))
    with tempfile.TemporaryDirectory(prefix="drawing-reader-site-") as cache:
        sets = build(args.out, [f.resolve() for f in files], Path(cache))
    for report in sets:
        print(f"{report.slug}: {len(report.idx.sheets)} sheet(s), {score_line(report.results)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
