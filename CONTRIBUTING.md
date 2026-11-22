# Contributing

Issues and pull requests are welcome. Please keep changes small and tested.

## Set up

```sh
uv sync --extra ocr
uv run pytest -n auto
uv run ruff check . && uv run ruff format --check .
uv run drawing-reader eval && uv run drawing-reader eval eval/questions_scan.yaml
```

Without the `ocr` extra the seven OCR end-to-end tests skip; CI runs both ways.

## Changing a parser or a rule

- Write the drafting convention the rule relies on in its docstring (`Convention: ...`) and add it
  to [docs/conventions.md](docs/conventions.md).
- Add a unit test on the smallest input that shows the behaviour: hand-built runs (`tests/support.py`)
  or a tiny PDF drawn with the drafting kit (`examples/drafting.py`).
- Run the acceptance questions. A scored question must not start failing. If a change fixes a
  known limit, `eval` reports it as `fixed`: remove its `known_limit` line.
- A new weakness becomes a question with `known_limit` and the reason, on a synthetic drawing that
  shows it. Only synthetic drawings are committed; keep any other drawings, and snapshots of them, in
  a local folder and use `eval/snapshot_regression.py`.

## Changing the examples

Edit `examples/generate.py` (or the kit in `examples/drafting.py`) and run
`uv run python examples/generate.py`. The output is deterministic; CI checks that the committed
PDFs match a fresh run. Expected answers in `eval/*.yaml` come from the drawing, not from the
reader's output.

## Adding a model provider

See [docs/providers.md](docs/providers.md#adding-a-provider): subclass `BaseProvider`, implement
`_complete`, register it, add its SDK as an optional extra, and test it with a mocked transport.
Never commit keys.

## Screenshots and the demo site

```sh
uv run --with playwright playwright install chromium
uv run --with playwright python scripts/screenshots.py   # docs/screenshots/
uv run python scripts/build_site.py                      # site/ (git-ignored)
```
