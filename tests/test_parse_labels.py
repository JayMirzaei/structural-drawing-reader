"""Member designations read as labels: plate thickness and plan size, less common section
families, and marks that only look like a designation."""

from __future__ import annotations

from drawing_reader.parse.sheet.parser import SheetParser
from support import make_run, make_sheet


def labels_of(*texts: str) -> dict:
    """Parse the texts as separate runs stacked down a sheet; return the label facts by value."""
    runs = [make_run(text, 60, 100 + 24 * i, 9) for i, text in enumerate(texts)]
    parser = SheetParser(make_sheet(runs))
    parser.parse_labels()
    return {f.value: f for f in parser.facts if f.kind == "label"}


def test_plate_label_is_split_into_thickness_and_plan_size():
    """A bare 'PL t' is a thickness callout with no plan size. 'PL AxBxC' gives both, and drafters
    write the thickness first or last: a plate is thinner than it is wide, so the smallest number is
    the thickness wherever it stands."""
    labels = labels_of("PL 280X190X9.5", "PL 16", "PL12x450x250", "PL10x140")

    def split(value):
        return labels[value].attrs["thickness"], labels[value].attrs["plan"]

    assert split("PL 280X190X9.5") == ("9.5", "280X190")
    assert split("PL 16") == ("16", "")
    assert split("PL12x450x250") == ("12", "450X250")
    assert split("PL10x140") == ("10", "140")


def test_pipe_pile_and_tee_families_are_recognised():
    """Three less common families: a pipe has a bare nominal size with no 'x' in it, an H-pile and a
    structural tee have two-letter prefixes."""
    labels = labels_of("PIPE6", "HP250x62", "WT155x39.5")
    assert labels["PIPE6"].attrs["family"] == "PIPE"
    assert labels["HP250x62"].attrs["family"] == "HP"
    assert labels["WT155x39.5"].attrs["family"] == "WT"


def test_a_bare_column_mark_is_not_a_channel():
    """'C2' on a framing plan is a column or pier mark. It has the shape of a sheet number and no
    'x' size, so it is not read as a channel section; a real channel designation still is."""
    labels = labels_of("C2", "C250x23")
    assert "C2" not in labels
    assert labels["C250x23"].attrs["family"] == "C"
