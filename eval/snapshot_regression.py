"""Check (or update) local behaviour snapshots for a local folder of drawings.

    uv run python eval/snapshot_regression.py <drawings_dir>            # report differences
    uv run python eval/snapshot_regression.py <drawings_dir> --update   # accept current behaviour

Snapshots are written to `<drawings_dir>/../snapshots` unless `--snapshots` says otherwise. Keep both
folders out of version control. See `drawing_reader.regression` for what a snapshot holds and why.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from drawing_reader.regression import check_folder

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".drawing_reader_cache"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("drawings_dir", type=Path)
    parser.add_argument("--snapshots", type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--update", action="store_true", help="overwrite the snapshots with current behaviour")
    args = parser.parse_args(argv)

    snapshots = args.snapshots or args.drawings_dir.parent / "snapshots"
    report = check_folder(args.drawings_dir, snapshots, args.cache, update=args.update)
    if not report:
        print(f"No PDFs found under {args.drawings_dir}.")
        return 0
    for pdf, diffs in report.items():
        print(f"{'updated' if args.update else 'DIFF' if diffs else 'ok':8} {pdf}")
        for d in diffs:
            print(f"   {d}")
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
