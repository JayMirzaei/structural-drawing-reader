"""Shared fixtures. Everything here is invented data: a small hand-built index, and the synthetic
example set from `examples/` read once per test session."""

from __future__ import annotations

import pytest
from PIL import Image

from drawing_reader import ocr
from drawing_reader.ingest import Document, ingest
from drawing_reader.parse import build_index
from drawing_reader.schema import Index, SheetMeta
from support import EXAMPLE_SCAN, EXAMPLE_SET, make_fact


@pytest.fixture
def idx(tmp_path) -> Index:
    """Two sheets of a made-up set: general notes on S-101, a base plate detail on S-501."""
    image = tmp_path / "sheet_2.png"
    Image.new("RGB", (400, 300), "white").save(image)
    sheets = [
        SheetMeta(page=1, number="S-101", title="GENERAL NOTES", text="GENERAL NOTES\nBOLTS: ASTM A325\nGROUT 30mm"),
        SheetMeta(
            page=2,
            number="S-501",
            title="BASE PLATE DETAILS",
            text="BASE PLATE: 38mm THICK\nANCHOR RODS 4-M24",
            image_path=str(image),
            width=400,
            height=300,
        ),
    ]
    facts = [
        make_fact("S-101.note.001", "note", "BOLTS: ASTM A325", "S-101", heading="General Notes", number="1"),
        make_fact("S-101.note.002", "note", "GROUT: 30mm THICK UNDER BASE PLATES", "S-101", number="2"),
        make_fact("S-501.note.001", "note", "BASE PLATE: 38mm THICK", "S-501"),
        make_fact(
            "S-501.label.001", "label", "W310X67", "S-501", family="W", section="W310X67", orientation="vertical"
        ),
        make_fact("S-501.dimension.001", "dimension", "410", "S-501", orientation="horizontal"),
    ]
    return Index(doc_id="doc123", source="made_up.pdf", is_vector=True, sheets=sheets, facts=facts)


@pytest.fixture(scope="session")
def example_cache(tmp_path_factory):
    """One cache folder per test session (and per xdist worker), so the examples are ingested once."""
    return tmp_path_factory.mktemp("example_cache")


@pytest.fixture(scope="session")
def platform_doc(example_cache) -> Document:
    """The synthetic access-platform set as ingested primitives. Do not modify it in a test."""
    return ingest(EXAMPLE_SET, example_cache)


@pytest.fixture(scope="session")
def platform(platform_doc) -> Index:
    """The fact index of the synthetic access-platform set (five vector sheets). Do not modify it in
    a test: it is shared by the whole session."""
    return build_index(platform_doc)


@pytest.fixture(scope="session")
def platform_scan(example_cache) -> Index:
    """The index of the rasterised framing plan, read by OCR. Skips when the OCR extra is missing."""
    if not ocr.available():
        pytest.skip("OCR engine not installed (install the `ocr` extra)")
    return build_index(ingest(EXAMPLE_SCAN, example_cache))
