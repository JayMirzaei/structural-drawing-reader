# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## 1.0.0

First public release.

### Reading

- Ingestion of vector PDFs into text runs (with writing direction), line segments, circles and a
  rendered image per page; rotated pages are read in their displayed orientation.
- Optional OCR path for scanned sheets (extra `ocr`): whole-page, tiled and rotated passes merged
  into the same text runs, with long lines recovered from the raster.
- On-disk cache keyed by the PDF's hash, with atomic writes and a format version; page images are
  stored relative to the cache folder, so a cache works from any working directory. OCR passes are
  cached separately from the primitives so a parser change never repeats the OCR.
- A file that is not a readable PDF (damaged, password-protected, empty, no pages) is reported in
  one line: exit status 2 in the CLI, a message in the app.
- Rule parsers for title blocks (bottom or right-hand strip), sheet titles, fields, scales and
  project location; three revision-table layouts; member designations (metric and imperial,
  plates, rods); grid bubbles, detail callouts, level markers and view titles; fillet-weld symbols;
  general notes, material clauses (material grades told apart from design, welding and coating
  standards) and design-load tables; dimensions with chain checks and a
  measured-scale cross-check; everything else kept as searchable text.
- A set-level pass for project fields, repeated title lines and references to sheets that are not
  in the set; repairs for scanned sets.
- The fact index (`Fact`, `SheetMeta`, `Index`): every fact with its sheet, box, source text and
  confidence, as JSON.

### Answering

- A router over 25 rule answerers (sheets, references, revisions, scales, project fields, members,
  materials, loads, geometry, callouts, welds, notes, keyword search), with confidence thresholds,
  OCR caps and caveats.
- A first-look summary of a set and warnings for sets outside the rules' scope.
- Evidence rendering: the cited facts boxed on the sheet image.
- Optional model fallback behind one provider contract: a local OpenAI-compatible server
  (llama.cpp, Ollama), Gemini, OpenAI and Anthropic. Replies are schema-constrained, may cite only
  existing fact ids, and are flagged when they state a number no cited fact contains. Drawing text
  is fenced in the prompt as untrusted data, never instructions.

### Tools

- Streamlit app: upload or load an example, provider picker, chat with confidence and caveats,
  evidence overlay per sheet, facts table. Drawing text and answers are shown with Markdown escaped.
- Settings in one module (`drawing_reader.settings`), read when used; the app reads `.env` first.
- Command line: `drawing-reader index | summary | ask | eval`.
- Acceptance questions with known limits kept visible (`eval/`; `reject` and `method` keys keep a
  too-broad or keyword-only answer from passing), a snapshot regression harness for
  drawing folders kept outside the repository, and an OCR fidelity script.
- Synthetic example drawings drawn by a script: a five-sheet vector set and a scanned sheet.
- Static demo site built from the examples, screenshots taken from the running app, Docker image
  and compose file, CI and Pages workflows.
