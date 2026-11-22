"""The ingest cache: files are written whole, so parallel readers of one cold cache never see a torn file."""

from __future__ import annotations

import importlib
import multiprocessing

import pytest

from drawing_reader.ingest.cache import write_atomic
from support import EXAMPLE_SET

pipeline = importlib.import_module("drawing_reader.ingest.pipeline")
cache_module = importlib.import_module("drawing_reader.ingest.cache")  # the package exports a function named `ingest`


def test_write_atomic_writes_the_whole_file_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "sub" / "primitives.json"
    write_atomic(target, "x" * 100_000)
    write_atomic(target, b"replaced")
    assert target.read_bytes() == b"replaced"
    assert [p.name for p in target.parent.iterdir()] == ["primitives.json"]


def test_a_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "sheet_1.png"
    target.write_bytes(b"old image")

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(cache_module.os, "replace", fail)
    with pytest.raises(OSError):
        write_atomic(target, b"new image")
    assert target.read_bytes() == b"old image"
    assert [p.name for p in tmp_path.iterdir()] == ["sheet_1.png"]


def _ingest_sheet_count(cache_dir: str) -> int | str:
    try:
        return len(pipeline.ingest(EXAMPLE_SET, cache_dir).sheets)
    except Exception as error:  # noqa: BLE001  reported, so the assertion shows what went wrong
        return f"{type(error).__name__}: {error}"


def test_processes_ingesting_one_pdf_into_a_cold_cache_all_succeed(tmp_path):
    """Workers that ingest the same PDF at once never open another worker's half-written sheet image or
    primitives file (the case of parallel test workers on a cold cache). Spawned, not forked: forking a
    multi-threaded process is unsafe."""
    cache = str(tmp_path / "cache")
    with multiprocessing.get_context("spawn").Pool(6) as pool:
        # a bounded wait: a stuck worker fails the test instead of hanging the run
        results = pool.map_async(_ingest_sheet_count, [cache] * 6).get(timeout=120)
    assert results == [5] * 6
    assert not list((tmp_path / "cache").rglob("*.tmp"))
