"""What the index of the synthetic access-platform set contains: sheets, member labels, references
to sheets outside the set, materials and elevation markers."""


def test_sheet_numbers_and_titles_come_from_the_title_blocks(platform):
    """Every sheet is numbered and titled from its own title block, in page order."""
    assert platform.sheet_numbers() == ["S-001", "S-101", "S-201", "S-301", "S-401"]
    assert platform.sheet_by_number("S-201").title == "FRAME ELEVATIONS"


def test_member_labels_carry_section_and_orientation(platform):
    """A section designation becomes a label fact, and a label drawn along a column reads as vertical."""
    sections = {f.attrs["section"] for f in platform.by_kind("label")}
    assert {"W310X39", "W250X33", "W200X27", "HSS152X152X9.5", "L102X102X9.5", "PL25X350X350", "PL10"} <= sections
    columns = [f for f in platform.by_kind("label") if f.sheet == "S-201" and f.attrs["section"] == "HSS152X152X9.5"]
    assert len(columns) == 5
    assert all(f.attrs["orientation"] == "vertical" for f in columns)


def test_only_the_guardrail_sheet_is_referenced_but_absent(platform):
    """Notes and callouts that point at a sheet outside the set are flagged; the others are not."""
    refs = platform.by_kind("reference", "callout")
    missing = {f.attrs["target_sheet"] for f in refs if not f.attrs["target_in_set"]}
    assert missing == {"S-501"}
    assert {f.sheet for f in refs if not f.attrs["target_in_set"]} == {"S-001", "S-101"}


def test_material_notes_and_elevation_markers(platform):
    """A 'COMPONENT: SPEC' note becomes a material fact; a level name over a value becomes an elevation."""
    specs = {m.attrs["component"]: m.attrs["spec"] for m in platform.by_kind("material")}
    assert specs["Anchor Rods"] == "ASTM F1554"
    assert specs["Bolts"] == "ASTM A325M"
    top_of_steel = {f.value for f in platform.by_kind("elevation") if f.attrs["name"] == "T.O. STEEL"}
    assert top_of_steel == {"3600"}
