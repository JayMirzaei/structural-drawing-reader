"""The `drawing-reader` command line, run in-process on the synthetic example set."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from drawing_reader.cli import main
from support import EXAMPLE_SET, ROOT


@pytest.fixture
def run(example_cache, capsys):
    """Run the CLI with the session's example cache; returns (exit code, stdout, stderr)."""

    def _run(*args: str) -> tuple[int, str, str]:
        code = main([*args[:1], "--cache", str(example_cache), *args[1:]])
        out, err = capsys.readouterr()
        return code, out, err

    return _run


def test_version(capsys):
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0 and capsys.readouterr().out.startswith("drawing-reader ")


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as stop:
        main([])
    assert stop.value.code == 2


def test_index_prints_the_fact_index_as_json(run):
    code, out, _ = run("index", str(EXAMPLE_SET))
    data = json.loads(out)
    assert code == 0
    assert [s["number"] for s in data["sheets"]] == ["S-001", "S-101", "S-201", "S-301", "S-401"]
    assert {"label", "dimension", "grid", "callout", "revision", "weld"} <= {f["kind"] for f in data["facts"]}


def test_index_writes_to_a_file(run, tmp_path):
    out_file = tmp_path / "index.json"
    code, out, err = run("index", str(EXAMPLE_SET), "--out", str(out_file))
    assert code == 0 and out == "" and "5 sheet(s)" in err
    assert json.loads(out_file.read_text())["project"]["Project No"] == "PN-4172"


def test_summary(run):
    code, out, _ = run("summary", str(EXAMPLE_SET))
    assert code == 0
    assert "5 sheet(s), vector PDF" in out and "S-301 — TYPICAL DETAILS" in out
    assert "Referenced but not in the set: S-501" in out and "**" not in out


def test_summary_as_markdown(run):
    code, out, _ = run("summary", str(EXAMPLE_SET), "--markdown")
    assert code == 0 and "**Referenced but not in the set:** S-501" in out


def test_ask_prints_the_answer_and_its_evidence(run):
    code, out, _ = run("ask", str(EXAMPLE_SET), "What is the live load?")
    assert code == 0
    assert "LIVE LOAD = 4.8 kPa" in out and "[rule:loads, confidence 0.90]" in out
    assert "Evidence:\n- [S-001.note." in out


def test_ask_writes_the_sheet_with_the_evidence_boxed(run, tmp_path):
    image = tmp_path / "evidence.png"
    code, out, _ = run("ask", str(EXAMPLE_SET), "What is the brace size?", "--evidence", str(image))
    assert code == 0
    # the brace is labelled on two sheets: one image per sheet, named after the sheet
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["evidence_S-201.png", "evidence_S-301.png"]
    with Image.open(tmp_path / "evidence_S-201.png") as img:
        pixels = np.asarray(img.convert("RGB"))
    red = int(np.all(pixels == (255, 0, 0), axis=-1).sum())
    assert red > 100  # the highlight box is drawn in pure red
    assert f"Evidence image: {tmp_path / 'evidence_S-201.png'}" in out


def test_ask_evidence_on_one_sheet_uses_the_given_name(run, tmp_path):
    image = tmp_path / "out.png"
    code, _, _ = run("ask", str(EXAMPLE_SET), "Who drew S-301?", "--evidence", str(image))
    assert code == 0 and image.is_file()


def test_ask_json(run):
    code, out, _ = run("ask", str(EXAMPLE_SET), "What grade are the anchor rods?", "--json")
    data = json.loads(out)
    assert code == 0 and data["method"] == "rule:materials" and data["sheets"] == ["S-001"]
    assert any("ASTM F1554" in f["value"] for f in data["facts"])
    assert data["evidence_images"] == []


def test_ask_with_an_unusable_provider_falls_back_to_the_rules(run, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out, err = run("ask", str(EXAMPLE_SET), "What is the live load?", "--provider", "anthropic")
    assert code == 0 and "4.8 kPa" in out
    assert "not available" in err and "rules only" in err


def test_a_missing_pdf_is_a_clear_error(run, tmp_path):
    code, out, err = run("summary", str(tmp_path / "absent.pdf"))
    assert code == 2 and out == "" and err.startswith("drawing-reader: no such file")


def test_eval_scores_the_acceptance_questions(run, monkeypatch):
    monkeypatch.chdir(ROOT)  # the default questions file is eval/questions.yaml
    code, out, _ = run("eval", "--quiet")
    assert code == 0
    assert out.startswith("== eval/questions.yaml (access_platform_set.pdf, rules only)")
    assert "status" in out.splitlines()[1] and "known limits:" in out


def test_eval_exit_status_reports_a_failing_question(run, tmp_path):
    questions = tmp_path / "q.yaml"
    questions.write_text(
        f"pdf: {EXAMPLE_SET}\nquestions:\n"
        "  - {id: right, q: 'What is the project number?', expect: [PN-4172]}\n"
        "  - {id: wrong, q: 'What is the project number?', expect: [PN-9999]}\n"
    )
    code, out, _ = run("eval", str(questions))
    assert code == 1
    assert "FAIL wrong" in out and "1/2 passed" in out


def test_eval_rejects_a_malformed_questions_file(run, tmp_path):
    questions = tmp_path / "bad.yaml"
    questions.write_text("questions: []\n")
    code, _, err = run("eval", str(questions))
    assert code == 2 and "expected a mapping" in err
