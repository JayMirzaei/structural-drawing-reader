"""The Streamlit app, run headless with Streamlit's own test harness on a one-sheet PDF made here."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from drawing_reader.providers import PROVIDERS

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture
def one_sheet_pdf(tmp_path) -> Path:
    """An invented sheet: three numbered notes, and a title block with a title and a sheet number."""
    doc = pymupdf.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((80, 100), "GENERAL NOTES:", fontsize=12)
    notes = (
        "1. ALL STRUCTURAL STEEL SHALL CONFORM TO CSA G40.21 350W.",
        "2. ALL BOLTS SHALL BE ASTM A325 UNLESS NOTED OTHERWISE.",
        "3. PROVIDE 30mm GROUT UNDER ALL BASE PLATES.",
    )
    for i, line in enumerate(notes):
        page.insert_text((80, 130 + 22 * i), line, fontsize=9)
    page.insert_text((900, 730), "GENERAL NOTES AND TYPICAL DETAILS", fontsize=14)
    page.insert_text((1120, 760), "S-101", fontsize=22)
    path = tmp_path / "one_sheet.pdf"
    doc.save(path)
    return path


@pytest.fixture
def app(tmp_path, monkeypatch) -> AppTest:
    # Streamlit runs the script as a module it installs as sys.modules["__main__"] and does not put the
    # old one back. Left in place, any later process started with "spawn" re-runs the app on start-up
    # (multiprocessing re-imports __main__ in each child) and dies, and the pool replaces it forever.
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    monkeypatch.setenv("DRAWING_READER_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("DRAWING_READER_ENV_FILE", str(tmp_path / "no.env"))
    for name in ("DRAWING_READER_PROVIDER", "DRAWING_READER_LOCAL_URL", "DRAWING_READER_MAX_LLM_CALLS"):
        monkeypatch.delenv(name, raising=False)
    for info in PROVIDERS.values():
        for name in info.key_env:
            monkeypatch.delenv(name, raising=False)
    return AppTest.from_file(APP, default_timeout=60)


def test_start_page_lists_every_provider(app):
    app.run()
    assert not app.exception
    assert app.header[0].value == "Load a drawing set to begin"
    assert app.sidebar.radio[0].options == ["Rules only (no LLM)", *(info.title for info in PROVIDERS.values())]


def test_a_question_is_answered_by_rules_with_evidence(app, one_sheet_pdf):
    app.session_state["pdf_path"] = str(one_sheet_pdf)
    app.run()
    assert not app.exception
    assert app.selectbox[0].options == ["S-101 — GENERAL NOTES AND TYPICAL DETAILS"]
    app.chat_input[0].set_value("What is the bolt grade?").run()
    assert not app.exception
    role, text, meta = app.session_state["history"][-1]
    assert role == "assistant" and "A325" in text
    assert meta["method"].startswith("rule:") and meta["sheets"] == ["S-101"] and meta["fact_ids"]
    assert app.session_state["highlight"] == meta["fact_ids"]


def test_a_provider_without_a_key_asks_for_one_and_falls_back_to_rules(app, one_sheet_pdf):
    app.session_state["pdf_path"] = str(one_sheet_pdf)
    app.run()
    app.sidebar.radio[0].set_value(PROVIDERS["anthropic"].title).run()
    assert not app.exception
    key_field = next(t for t in app.sidebar.text_input if t.label == "Anthropic Claude API key")
    assert key_field.value == ""
    assert any("no API key" in w.value for w in app.sidebar.warning)
    key_field.set_value("typed-in-the-browser-0000").run()
    assert not app.exception and not any("no API key" in w.value for w in app.sidebar.warning)
    shown = " ".join(str(getattr(e, "value", "")) for e in app.main) + " ".join(
        str(m.value) for m in app.sidebar.markdown
    )
    assert "typed-in-the-browser-0000" not in shown  # the key is never echoed back


def test_an_unreachable_local_server_is_reported(app, one_sheet_pdf):
    app.session_state["pdf_path"] = str(one_sheet_pdf)
    app.run()
    app.sidebar.radio[0].set_value(PROVIDERS["local"].title).run()
    url = next(t for t in app.sidebar.text_input if t.label == "Server URL")
    url.set_value("http://127.0.0.1:9").run()  # the discard port: nothing listens
    assert not app.exception
    assert any("not reachable at http://127.0.0.1:9" in w.value for w in app.sidebar.warning)


def test_the_vector_example_is_the_default_and_loads_from_the_sidebar_button(app):
    app.run()
    options = app.sidebar.selectbox[0].options
    assert options[0] == "access platform set" and options[1].startswith("access platform scan")
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert app.selectbox[0].options[0] == "S-001 — GENERAL NOTES"
    app.chat_input[0].set_value("What is the live load?").run()
    role, text, meta = app.session_state["history"][-1]
    assert role == "assistant" and "4.8 kPa" in text and meta["sheets"] == ["S-001"]


def test_the_scan_example_is_labelled_when_ocr_is_missing(app, monkeypatch):
    from drawing_reader import ocr

    monkeypatch.setattr(ocr, "available", lambda: False)
    app.run()
    assert app.sidebar.selectbox[0].options[1] == "access platform scan (needs the ocr extra)"


def test_the_provider_set_in_the_environment_is_preselected(app, monkeypatch):
    monkeypatch.setenv("DRAWING_READER_PROVIDER", "openai")
    app.run()
    assert not app.exception
    assert app.sidebar.radio[0].value == PROVIDERS["openai"].title


@pytest.mark.parametrize(
    "content",
    [b"", b"not a pdf at all\n" * 10],
    ids=["empty", "not-a-pdf"],
)
def test_an_unreadable_file_gets_a_message_not_a_traceback(app, tmp_path, content):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(content)
    app.session_state["pdf_path"] = str(bad)
    app.run()
    assert not app.exception
    assert any("cannot be read as a drawing set" in e.value for e in app.error)


def test_drawing_text_cannot_inject_markdown(app, tmp_path):
    """A note holding Markdown image syntax is shown as text: the page never gets an image link."""
    doc = pymupdf.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((80, 100), "GENERAL NOTES:", fontsize=12)
    page.insert_text((80, 130), "1. BOLTS ![x](https://example.invalid/t.png) SHALL BE A325.", fontsize=9)
    page.insert_text((80, 152), "2. GROUT <img src=x> SHALL BE NON-SHRINK.", fontsize=9)
    page.insert_text((1120, 760), "S-101", fontsize=22)
    path = tmp_path / "hostile.pdf"
    doc.save(path)
    app.session_state["pdf_path"] = str(path)
    app.run()
    app.chat_input[0].set_value("What are the general notes?").run()
    assert not app.exception
    rendered = [m.value for m in app.markdown]
    assert any("A325" in m and "example.invalid" in m for m in rendered)  # the text is shown, as text
    assert not any(re.search(r"(?<!\\)!(?<!\\)\[|(?<!\\)<img", m) for m in rendered)


def test_a_low_text_pdf_says_whether_ocr_would_help(app, tmp_path, monkeypatch):
    from drawing_reader import ocr

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "S-1", fontsize=10)
    path = tmp_path / "nearly_blank.pdf"
    doc.save(path)
    monkeypatch.setattr(ocr, "available", lambda: True)
    app.session_state["pdf_path"] = str(path)
    app.run()
    warnings = " ".join(w.value for w in app.warning)
    assert "OCR is not installed" not in warnings and "very little text" in warnings


def test_settings_set_after_the_first_run_are_honoured(app, one_sheet_pdf, monkeypatch):
    """The local server URL is read when the sidebar is drawn, not frozen when a module was first imported."""
    app.session_state["pdf_path"] = str(one_sheet_pdf)
    app.run()
    monkeypatch.setenv("DRAWING_READER_LOCAL_URL", "http://127.0.0.1:9")
    app.sidebar.radio[0].set_value(PROVIDERS["local"].title).run()
    url = next(t for t in app.sidebar.text_input if t.label == "Server URL")
    assert url.value == "http://127.0.0.1:9"
