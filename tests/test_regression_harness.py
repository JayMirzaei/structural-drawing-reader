"""The snapshot regression harness: it freezes what the reader does on a folder of PDFs and later
reports what changed. Tested on the synthetic example set and on small drawings made in `tmp_path`."""

from __future__ import annotations

import json
import shutil

import pytest

from drafting import title_block
from drawing_reader import regression
from drawing_reader.regression import (
    GENERIC_PROBES,
    build_snapshot,
    check_folder,
    diff_snapshots,
    discover_pdfs,
    is_slow_pdf,
    snapshot_path,
)
from support import EXAMPLE_SET, EXAMPLES, draw_pdf


def one_sheet(number, title, note="ALL BOLTS TO BE ASTM A325M"):
    """A drawing function for `draw_pdf`: a title block and one numbered note."""

    def draw(canvas):
        title_block(
            canvas,
            client="HARLOW CREEK REGIONAL UTILITIES",
            project=["PUMP HOUSE ROOF"],
            address="12 MILL LANE, LARKSPUR FALLS, MB",
            fields={"PROJECT NO.": "PN-5208", "DATE": "2030-10-07", "SCALE": "1:50"},
            revisions=[("0", "ISSUED FOR CONSTRUCTION", "2030-10-07")],
            title=[title],
            number=number,
        )
        canvas.notes(60, 60, "GENERAL NOTES:", [note], width=300)

    return draw


@pytest.fixture(scope="module")
def example_snapshot(tmp_path_factory):
    """The snapshot of the example set, built once for this module."""
    return build_snapshot(EXAMPLE_SET, EXAMPLES, tmp_path_factory.mktemp("snapshot_cache"))


@pytest.fixture
def drawings(tmp_path):
    """A folder holding one drawn one-sheet PDF, with folders for its snapshots and cache."""
    folder = tmp_path / "drawings"
    folder.mkdir()
    draw_pdf(folder / "roof.pdf", one_sheet("S-101", "ROOF FRAMING PLAN"))
    return folder, tmp_path / "snapshots", tmp_path / "cache"


# --- finding the drawings ---------------------------------------------------------------------------


def test_discover_finds_pdfs_in_subfolders_in_a_stable_order(tmp_path):
    for name in ("b/second.pdf", "a/first.pdf", "third.pdf", "a/readme.txt"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"")
    found = [str(p.relative_to(tmp_path)) for p in discover_pdfs(tmp_path)]
    assert found == ["a/first.pdf", "b/second.pdf", "third.pdf"]


def test_discover_leaves_out_excluded_file_names_and_survives_a_missing_folder(tmp_path):
    (tmp_path / "keep.pdf").write_bytes(b"")
    (tmp_path / "skip.pdf").write_bytes(b"")
    assert [p.name for p in discover_pdfs(tmp_path, exclude=("skip.pdf",))] == ["keep.pdf"]
    assert discover_pdfs(tmp_path / "not_there") == []


def test_discover_finds_the_committed_examples():
    assert EXAMPLE_SET in discover_pdfs(EXAMPLES)


def test_snapshot_path_flattens_the_relative_path_into_one_file_name(tmp_path):
    pdf = tmp_path / "drawings" / "Phase 2" / "Roof (rev B).pdf"
    assert (
        snapshot_path(pdf, tmp_path / "drawings", tmp_path / "snaps")
        == tmp_path / "snaps" / "Phase_2_Roof_rev_B_pdf.json"
    )


def test_two_pdfs_with_one_name_in_different_folders_get_different_snapshots(tmp_path):
    a = snapshot_path(tmp_path / "east" / "plan.pdf", tmp_path, tmp_path / "snaps")
    b = snapshot_path(tmp_path / "west" / "plan.pdf", tmp_path, tmp_path / "snaps")
    assert a != b


def test_a_pdf_is_slow_only_above_the_size_limit(tmp_path, monkeypatch):
    """File size stands in for ingestion cost, so big combined sets can sit in an opt-in tier."""
    pdf = tmp_path / "small.pdf"
    pdf.write_bytes(b"x" * 2048)
    assert not is_slow_pdf(pdf) and not is_slow_pdf(EXAMPLE_SET)
    monkeypatch.setattr(regression, "SLOW_FILE_SIZE_MB", 0.001)
    assert is_slow_pdf(pdf)


# --- what a snapshot holds --------------------------------------------------------------------------


def test_snapshot_of_the_example_set_counts_sheets_and_facts(example_snapshot, platform):
    assert example_snapshot["source"] == EXAMPLE_SET.name
    assert example_snapshot["is_vector"] is True and example_snapshot["sheet_count"] == 5
    counts = example_snapshot["fact_counts"]
    assert list(counts) == sorted(counts)
    assert sum(counts.values()) == len(platform.facts)
    assert counts["sheet"] == 5 and counts["titleblock"] == len(platform.by_kind("titleblock"))


def test_snapshot_reports_nothing_missing_on_a_complete_set(example_snapshot, platform):
    """The sparseness counts make an empty title block or a blank title show up in a diff."""
    assert example_snapshot["sparseness"] == {
        "blank_title_sheets": 0,
        "sheets_with_no_facts_at_all": 0,
        "sheets_with_no_titleblock_facts": 0,
        "project_fields_found": len(platform.project),
    }
    assert example_snapshot["scope_advice"] == []


def test_snapshot_records_the_answer_to_every_generic_question(example_snapshot):
    probes = example_snapshot["probes"]
    assert list(probes) == GENERIC_PROBES
    assert all(set(p) == {"rule", "confidence", "text"} for p in probes.values())
    assert probes["What is the project number?"]["rule"].startswith("rule:")
    assert "PN-4172" in probes["What is the project number?"]["text"]
    assert "S-301" in probes["List the sheets and their titles."]["text"]


def test_a_snapshot_survives_a_trip_through_json(example_snapshot):
    assert json.loads(json.dumps(example_snapshot)) == example_snapshot


def test_building_the_same_snapshot_twice_changes_nothing(example_snapshot, tmp_path):
    """Reading is deterministic, so an unchanged reader on an unchanged PDF is silent."""
    again = build_snapshot(EXAMPLE_SET, EXAMPLES, tmp_path / "other_cache")
    assert diff_snapshots(example_snapshot, again) == []


# --- what a difference looks like ---------------------------------------------------------------------


def changed(snapshot, **top_level):
    copy = json.loads(json.dumps(snapshot))
    copy.update(top_level)
    return copy


def test_a_changed_sheet_count_and_text_kind_are_reported(example_snapshot):
    new = changed(example_snapshot, sheet_count=4, is_vector=False)
    assert diff_snapshots(example_snapshot, new) == ["sheet_count: 5 -> 4", "is_vector: True -> False"]


def test_a_changed_fact_count_names_the_kind(example_snapshot):
    new = changed(example_snapshot)
    was = new["fact_counts"]["dimension"]
    new["fact_counts"]["dimension"] = was - 2
    del new["fact_counts"]["weld"]
    new["fact_counts"]["stamp"] = 1
    assert diff_snapshots(example_snapshot, new) == [
        f"fact_counts[dimension]: {was} -> {was - 2}",
        "fact_counts[stamp]: 0 -> 1",
        f"fact_counts[weld]: {example_snapshot['fact_counts']['weld']} -> 0",
    ]


def test_a_sheet_that_lost_its_title_is_reported(example_snapshot):
    new = changed(example_snapshot)
    new["sparseness"]["blank_title_sheets"] = 1
    assert diff_snapshots(example_snapshot, new) == ["sparseness[blank_title_sheets]: 0 -> 1"]


def test_a_changed_answer_shows_the_old_and_the_new(example_snapshot):
    question = "What is the project number?"
    new = changed(example_snapshot)
    new["probes"][question] = {"rule": "none", "confidence": 0.0, "text": ""}
    (diff,) = diff_snapshots(example_snapshot, new)
    assert diff.startswith(f"probe {question!r}:")
    assert "PN-4172" in diff.split("now:")[0] and "'rule': 'none'" in diff.split("now:")[1]


def test_new_scope_advice_is_reported(example_snapshot):
    new = changed(example_snapshot, scope_advice=["This set looks multi-discipline."])
    (diff,) = diff_snapshots(example_snapshot, new)
    assert diff.startswith("scope_advice: [] -> ")


# --- a folder of drawings -----------------------------------------------------------------------------


def test_a_pdf_without_a_snapshot_says_so_and_writes_nothing(drawings):
    folder, snapshots, cache = drawings
    assert check_folder(folder, snapshots, cache) == {"roof.pdf": ["no snapshot yet: update to create one"]}
    assert not snapshots.exists()


def test_update_writes_the_snapshot_and_the_next_check_is_silent(drawings):
    folder, snapshots, cache = drawings
    assert check_folder(folder, snapshots, cache, update=True) == {"roof.pdf": []}
    saved = json.loads(snapshot_path(folder / "roof.pdf", folder, snapshots).read_text())
    assert saved["sheet_count"] == 1 and saved["source"] == "roof.pdf"
    assert check_folder(folder, snapshots, cache) == {"roof.pdf": []}


def test_a_drawing_that_changed_since_its_snapshot_is_reported(drawings):
    """The PDF is redrawn with another title and a second note: the list answer and a fact count
    differ from the snapshot."""
    folder, snapshots, cache = drawings
    check_folder(folder, snapshots, cache, update=True)
    draw_pdf(folder / "roof.pdf", one_sheet("S-101", "ROOF BRACING PLAN", note="SEE S-501 FOR BASE PLATE DETAILS"))
    diffs = check_folder(folder, snapshots, cache)["roof.pdf"]
    assert any(d.startswith("probe 'List the sheets and their titles.'") and "ROOF BRACING PLAN" in d for d in diffs)
    assert any(d.startswith("fact_counts[") for d in diffs)


def test_each_pdf_in_the_folder_is_checked_on_its_own(drawings):
    """One unchanged file, one changed and one new: three separate verdicts, keyed by relative path."""
    folder, snapshots, cache = drawings
    (folder / "set").mkdir()
    shutil.copy(folder / "roof.pdf", folder / "set" / "copy.pdf")
    check_folder(folder, snapshots, cache, update=True)
    draw_pdf(folder / "set" / "copy.pdf", one_sheet("S-102", "FLOOR FRAMING PLAN"))
    draw_pdf(folder / "new.pdf", one_sheet("S-103", "STAIR DETAILS"))
    report = check_folder(folder, snapshots, cache)
    assert list(report) == ["new.pdf", "roof.pdf", "set/copy.pdf"]
    assert report["roof.pdf"] == [] and report["new.pdf"] == ["no snapshot yet: update to create one"]
    assert report["set/copy.pdf"] != []
