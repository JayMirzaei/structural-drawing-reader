# Evaluation

## What is measured

`drawing-reader eval` asks a drawing set a list of questions and checks each answer. The questions
live in YAML next to the drawing they are about:

```yaml
pdf: ../examples/access_platform_set.pdf      # relative to the questions file
questions:
  - id: drawn-by-sheet
    topic: title block
    q: Who drew S-301?
    expect: [HZK]          # every string must appear in the answer (case-insensitive)
    reject: [QEV]          # none of these may appear (here: the set-wide drafter)
    sheets: [S-301]        # the cited evidence must include these sheets
  - id: anchor-rod-diameter
    q: What is the anchor rod diameter?
    expect: [Ø20]
    method: rule:component-spec   # the answer must come from this rule, not the keyword fallback
  - id: bay-width
    topic: geometry
    q: What is the bay width between grid A and B?
    expect: ["6000"]
    known_limit: >-        # the reader gets this wrong today, and here is why
      The grid rule claims any question that names grid lines and lists the grids ...
```

A question passes when the answer contains every `expect` string, none of the `reject` strings,
cites evidence on every listed sheet and, when `method` is given, comes from that rule. The `sheets`
check matters: an answer that names the right value but cites the wrong place does not pass.
`reject` keeps a too-broad answer from passing (a grade question must not also list the design and
galvanizing standards), and `method` keeps a question from passing on the keyword fallback
(`rule:text-search`), which lists every note line that shares a word with the question.

A question marked `known_limit` is still asked. It is reported as `limit` while it fails and as
`fixed` once it passes, so a weakness is never hidden and a fix is noticed. Only questions without
`known_limit` are scored; a failure among them is a regression and makes the command exit with
status 1 (CI runs it).

The expected values are taken from the drawing as drawn (the generator script that drew it), not
from the reader's output. The drawing was not adjusted to make a question pass.

```sh
uv run drawing-reader eval                               # eval/questions.yaml, the vector set
uv run drawing-reader eval eval/questions_scan.yaml      # the scanned sheet (needs --extra ocr)
uv run drawing-reader eval --provider openai             # questions the rules miss go to a model
```

Rules-only runs are deterministic: two runs give byte-identical output.

## The examples

The drawings are synthetic, drawn by `examples/generate.py` with a small drafting kit
(`examples/drafting.py`): an invented "conveyor access platform", five vector sheets drawn to
scale (general notes and design data; a framing plan; two frame elevations; three typical details on
a sheet stored rotated; a column schedule and an isometric view) and the framing plan again as an
image-only office scan (grey paper, slight skew, blur, speckle, JPEG). They exercise title blocks,
revision tables, general notes, material clauses, load tables, member labels, grids, levels,
dimensions and chains, callouts, weld symbols, view titles, a reference to a sheet that is not in
the set, and the OCR path.

## Score (rules only, version 1.0.0)

| Set | Questions | Scored | Pass | Known limits (still failing) |
|---|---|---|---|---|
| `access_platform_set.pdf` (vector, 5 sheets) | 54 | 43 | 43 | 11 |
| `access_platform_scan.pdf` (scan, 1 sheet, OCR) | 8 | 5 | 5 | 3 |
| **Total** | **62** | **48** | **48** | **14** |

So the rules answer 48 of the 62 questions correctly, with evidence on the right sheet; the other
14 are the known limits below. By topic, the vector set covers sheets and references (8 questions),
title block (7), revisions (3), scale (2), members (5), materials (7), loads (3), notes (3), geometry
(8), welds (2), callouts (4), a schedule lookup (1), and one question about something that is not on
the drawings, which must be answered "not found".

This is a score on one small, clean, invented set that the rules were checked against while it was
written. It shows that the pipeline works end to end and where it fails; it is not a general accuracy
figure: drawing sets vary far more. No model-assisted score is reported, because no
provider was run against a live API for this release.

## Known limits

Each of these is a question in the eval files, failing today, with the reason in the file.

**Vector set**

1. **Columns** (`column-size`): "What size are the columns?" Member roles come from label
   orientation. In a plan, beams drawn up the sheet carry vertical labels, so the plan's W250X33 and
   W200X27 beams are listed as columns next to the real HSS columns.
2. **Beams** (`beam-sizes`): a horizontal HSS label in a detail and the schedule rows are taken for
   beams. The orientation rule cannot tell a schedule cell or a leader label from a member drawn
   along its length.
3. **"What bolts are used?"** (`bolts-plain`): the materials rule waits for a grade or size word;
   this question names neither, and no other rule claims it, so the reader says it found nothing.
4. **Bay width between named grids** (`bay-width`): the grid rule claims any question that names
   grid lines and lists the grids. Dimensions are not tied to the grid lines they run between.
5. **Overall length of a named object** (`overall-length`): "length of the platform" only matches
   dimensions through a view title; no view is called "platform", and the overall dimension carries
   no name of its own.
6. **Base plate thickness** (`base-plate-thickness`): the thickness is in the plate label
   `PL25X350X350` in the base plate detail, but the question names no detail, and the component rule
   reads thicknesses from note text only.
7. **"What details are called out on S-101?"** (`callouts-on-sheet-details`): the callout rule
   triggers on "callout(s)" or "detail <n>"; this wording reaches no rule.
8. **Schedule row lookup** (`schedule-row`): schedule cells are recognised (so their numbers are not
   taken for dimensions), but rows are not read as records, so no rule can answer "which mark is at
   grid B-1".
9. **Grout thickness** (`grout`): the grout rule reads a thickness only when "mm" follows the number;
   this set writes "25 THICK" with the unit stated once in the general notes. Only the keyword
   fallback finds the note.
10. **Base plate size** (`base-plate-size`): the answer lists the detail's dimension strings (350,
    250, 50, Ø26) instead of the plate's own label `PL25X350X350`, so the plan size is not stated.
11. **Anchor rod diameter** (`anchor-rod-diameter`): "Ø20 THREADED ROD ANCHORS" puts the diameter
    before the component name, which the component rule does not read; only the keyword fallback
    finds the line, among five unrelated ones.

**Scan**

12. **Plan note on a scan** (`scan-plan-note`): OCR drops the space in the heading ("PLANNOTES"), so
    the note lookup cannot match "plan note".
13. **Project location on a scan** (`scan-location`): OCR runs words together ("45QUARRY ROAD"); the
    address is found, but the location question does not reach it with enough confidence.
14. **Grids on a scan** (`scan-grids`): circles are not recovered from a raster, so grid bubbles are
    not found on a scan.

**Also known, outside the eval files**

- `tests/test_qa_callout_counts.py` holds one strict `xfail`: "How many callouts reference the base
  plate detail?" falls through to a listing of every callout, because the title match needs every
  content word of the question in the view title and "detail" is not in "COLUMN BASE PLATE".
- A fractional size in a material clause (`3/4"`) is kept as `4"` in the clause's size attribute.
- A title line that holds an all-consonant tag can shorten a stacked sheet title.

## Other measurements in `eval/`

- `eval/ocr_fidelity.py <vector.pdf>`: rasterises a vector PDF, runs the OCR path on the image, and
  compares each kind of fact with what the text layer gives. Used to tune the OCR passes
  (`--set NAME=VALUE` overrides an `ocr.config` constant for one run).
- `eval/snapshot_regression.py <drawings_dir>`: behaviour snapshots for a local folder of drawings
  kept outside the repository (see [architecture.md](architecture.md#test-layers)).
