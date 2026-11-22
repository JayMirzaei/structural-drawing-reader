"""Files that are not readable drawing sets, and a cache used from another working directory."""

from __future__ import annotations

import os

import pymupdf
import pytest

from drawing_reader.cli import main
from drawing_reader.ingest import UnreadablePDF, ingest
from drawing_reader.parse import build_index
from drawing_reader.qa import render_sheet
from support import EXAMPLE_SET


def _encrypted(path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "SECRET")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    doc.close()


BAD_FILES = {
    "empty": (lambda p: p.write_bytes(b""), "empty"),
    "not a pdf": (lambda p: p.write_bytes(b"this is a text file, not a drawing\n" * 20), "not a PDF"),
    "markdown": (lambda p: p.write_bytes(b"# Notes\n\n- ALL STEEL SHALL BE CSA G40.21 350W\n" * 30), "not a PDF"),
    "png": (lambda p: p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 200), "not a PDF"),
    "broken pdf": (lambda p: p.write_bytes(b"%PDF-1.7\n" + b"garbage " * 50), "not a readable PDF"),
    "truncated": (lambda p: p.write_bytes(EXAMPLE_SET.read_bytes()[:400]), "not a readable PDF"),
    "encrypted": (_encrypted, "password-protected"),
}


@pytest.mark.parametrize("case", sorted(BAD_FILES))
def test_an_unreadable_file_raises_one_clear_error(tmp_path, case):
    make, reason = BAD_FILES[case]
    pdf = tmp_path / "upload.pdf"
    make(pdf)
    with pytest.raises(UnreadablePDF, match=reason):
        ingest(pdf, tmp_path / "cache")
    assert not list((tmp_path / "cache").glob("*/primitives.json"))


def test_the_cli_reports_an_unreadable_file_without_a_traceback(tmp_path, capsys):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.7\n garbage")
    code = main(["summary", str(pdf), "--cache", str(tmp_path / "cache")])
    err = capsys.readouterr().err
    assert code == 2
    assert "cannot read" in err and "broken.pdf" in err and "Traceback" not in err


def test_a_cache_filled_from_one_folder_works_from_another(tmp_path, monkeypatch):
    """Image paths in the cache are stored relative to the document's cache folder, so evidence renders
    whichever directory the reader is started from."""
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    ingest(EXAMPLE_SET, "relative_cache")  # a relative cache path, as the CLI default is
    stored = next((first / "relative_cache").glob("*/primitives.json")).read_text()
    assert str(tmp_path) not in stored and '"image_path": "sheet_1.png"' in stored
    monkeypatch.chdir(second)
    doc = ingest(EXAMPLE_SET, first / "relative_cache")
    assert os.path.isabs(doc.sheets[0].image_path)
    idx = build_index(doc)
    assert render_sheet(idx, idx.sheet_numbers()[0], {"label"}, [idx.facts[0].id]) is not None
