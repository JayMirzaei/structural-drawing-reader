"""Draw the example drawing sets.

    uv run python examples/generate.py

Writes, next to this file:

- `access_platform_set.pdf`: five vector sheets of a small steel access platform (general notes,
  framing plan, elevations, details, schedule and isometric). The details sheet is stored the way
  plotters often write a landscape sheet: a portrait page with a /Rotate entry.
- `access_platform_scan.pdf`: the framing plan as a picture only (no text layer), for the OCR path.

Everything here is invented: the project, the client, the address, the frame and every number. The
section names (W310X39, HSS152X152X9.5 ...) and the material standards are public designations. The
platform is drawn to scale so that the reader's checks (dimension strings that add up, a scale
measured from the dimensions) have something real to check.
"""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf

from drafting import (
    BOLD,
    HEAVY,
    MEDIUM,
    Canvas,
    new_sheet,
    paper,
    plot_rotated,
    rasterise,
    save,
    title_block,
)

HERE = Path(__file__).resolve().parent

CLIENT = "HARLOW CREEK REGIONAL UTILITIES"
PROJECT = ("HARLOW CREEK TRANSFER STATION", "CONVEYOR ACCESS PLATFORM")
ADDRESS = "45 QUARRY ROAD, LARKSPUR FALLS, MB"
PROJECT_NO = "PN-4172"

# The platform: three frames along grids A, B, C and two column lines 1 and 2.
BAYS = (6000, 4500)  # A-B, B-C
WIDTH = 5200  # between grids 1 and 2
TOP_OF_STEEL = 3600
TOP_OF_GUARD = 4700
BRACE_ANGLE = round(math.degrees(math.atan2(TOP_OF_STEEL, BAYS[0])), 1)  # the brace runs corner to corner of bay A-B

COLUMN = "HSS152X152X9.5"
MAIN_BEAM = "W310X39"
END_BEAM = "W250X33"
INFILL_BEAM = "W200X27"
BRACE = "L102X102X9.5"
BASE_PLATE = "PL25X350X350"
SHEAR_TAB = "PL10X100X230"

ISSUES = (
    ("A", "ISSUED FOR REVIEW", "2030-02-04"),
    ("B", "ISSUED FOR APPROVAL", "2030-03-26"),
    ("0", "ISSUED FOR CONSTRUCTION", "2030-05-08"),
)
REVISED = ("1", "REVISED ANCHOR ROD SIZE", "2030-06-19")

SHEETS = {
    "S-001": ("GENERAL NOTES",),
    "S-101": ("PLATFORM FRAMING PLAN",),
    "S-201": ("FRAME ELEVATIONS",),
    "S-301": ("TYPICAL DETAILS",),
    "S-401": ("COLUMN SCHEDULE", "AND ISOMETRIC VIEW"),
}


def frame(c: Canvas, number: str, scale: str, revisions=ISSUES, drawn: str = "QEV", date: str = "2030-05-08") -> None:
    title_block(
        c,
        client=CLIENT,
        project=PROJECT,
        address=ADDRESS,
        fields={
            "PROJECT NO.": PROJECT_NO,
            "DATE": date,
            "SCALE": scale,
            "DRAWN BY": drawn,
            "CHECKED BY": "ALK",
            "APPROVED BY": "TMW",
        },
        revisions=revisions,
        title=SHEETS[number],
        number=number,
    )


# ---- S-001 -----------------------------------------------------------------------------------


def general_notes(c: Canvas) -> None:
    frame(c, "S-001", "N.T.S.")
    y = c.notes(
        40,
        50,
        "GENERAL NOTES:",
        [
            "ALL DIMENSIONS ARE IN MILLIMETRES UNLESS NOTED OTHERWISE.",
            "ELEVATIONS ARE IN MILLIMETRES ABOVE THE TOP OF THE EXISTING SLAB (EL. 0).",
            "DO NOT SCALE THE DRAWINGS.",
            "VERIFY ALL EXISTING DIMENSIONS ON SITE BEFORE FABRICATION.",
            "SEE DWG S-501 FOR GUARDRAIL AND LADDER DETAILS.",
            "SEE DETAIL 1/S-301 FOR THE TYPICAL COLUMN BASE PLATE.",
            "THIS SET IS A SYNTHETIC EXAMPLE DRAWN BY A SCRIPT. IT DOES NOT SHOW A REAL STRUCTURE.",
        ],
    )
    c.notes(
        40,
        y + 10,
        "DESIGN CRITERIA:",
        [
            "DESIGN CODE: NATIONAL BUILDING CODE OF CANADA 2020.",
            "STRUCTURAL STEEL DESIGN TO CSA S16.",
            "IMPORTANCE CATEGORY: NORMAL.",
            "SEISMIC DATA: Sa(0.2) = 0.12, SITE CLASS: C.",
            "DEFLECTION OF PLATFORM BEAMS UNDER LIVE LOAD IS LIMITED TO SPAN/360.",
        ],
    )
    y = c.notes(
        430,
        50,
        "MATERIALS:",
        [
            "BEAMS: CSA G40.21 350W, Fy=350 MPa",
            "HSS COLUMNS: CSA G40.21 350W CLASS C, Fy=350 MPa",
            "ANGLES AND PLATES: CSA G40.21 300W, Fy=300 MPa",
            "ANCHOR RODS: ASTM F1554 GRADE 36, Fy=248 MPa",
            "BOLTS: M20 ASTM A325M UNO",
            "WELDING ELECTRODES: E49XX TO CSA W48",
            "GRATING: 32 DEEP SERRATED BAR GRATING, GALVANIZED, BEARING BARS AT 30 CENTRES",
            "GROUT: NON-SHRINK CEMENTITIOUS GROUT, 25 THICK, 35 MPa MINIMUM AT 28 DAYS",
            "EXISTING SLAB CONCRETE: f'c = 30 MPa (ASSUMED, TO BE CONFIRMED ON SITE)",
        ],
    )
    c.notes(
        430,
        y + 10,
        "STRUCTURAL STEEL:",
        [
            "FABRICATION AND ERECTION SHALL CONFORM TO CSA S16.",
            "ALL WELDS SHALL BE 6 FILLET WELDS ALL AROUND UNLESS NOTED OTHERWISE.",
            "BOLTED CONNECTIONS SHALL BE BEARING TYPE, SNUG TIGHTENED, UNLESS NOTED OTHERWISE.",
            "HOT DIP GALVANIZE ALL STEEL AFTER FABRICATION TO CSA G164.",
            "PROVIDE A 6 CAP PLATE ON EVERY HSS COLUMN.",
            "SUBMIT SHOP DRAWINGS FOR REVIEW BEFORE FABRICATION.",
        ],
    )
    c.text(820, 50, "DESIGN LOADS:", 9, font=BOLD)
    loads = (
        ("LIVE LOAD", "4.8 kPa"),
        ("DEAD LOAD", "1.1 kPa"),
        ("CONCENTRATED LOAD", "4.5 kN"),
        ("GUARD LOAD", "0.75 kN/m"),
    )
    for i, (name, value) in enumerate(loads):
        c.text(828, 66 + 12 * i, name, 7)
        c.text(960, 66 + 12 * i, value, 7)
    c.text(820, 150, "DRAWING INDEX:", 9, font=BOLD)
    for i, (number, title) in enumerate(SHEETS.items()):
        c.text(828, 166 + 11 * i, number, 7)
        c.text(870, 166 + 11 * i, " ".join(title), 7)
    c.notes(
        820,
        250,
        "ABBREVIATIONS:",
        [
            "T.O. - TOP OF",
            "U/S - UNDERSIDE OF",
            "UNO - UNLESS NOTED OTHERWISE",
            "TYP. - TYPICAL",
            "EL. - ELEVATION",
        ],
        numbered=False,
    )


# ---- S-101 -----------------------------------------------------------------------------------


def framing_plan(c: Canvas) -> None:
    frame(c, "S-101", "1:50")
    scale = 50
    xa, y2 = 230.0, 200.0  # grid A, grid 2 (grid 1 is the lower column line on the sheet)
    xs = [xa, xa + paper(BAYS[0], scale), xa + paper(sum(BAYS), scale)]
    y1 = y2 + paper(WIDTH, scale)

    for x, name in zip(xs, "ABC", strict=True):
        c.grid_line((x, y2 - 88), (x, y1 + 34))
        c.grid_bubble((x, y2 - 100), name)
    for y, name in ((y1, "1"), (y2, "2")):
        c.grid_line((xs[0] - 96, y), (xs[-1] + 40, y))
        c.grid_bubble((xs[0] - 108, y), name)

    for y in (y1, y2):  # main beams along grids 1 and 2
        c.line((xs[0], y), (xs[-1], y), HEAVY)
    for x in xs:  # beams along the lettered grids
        c.line((x, y1), (x, y2), HEAVY)
        for y in (y1, y2):
            c.filled_rect(x - 3.2, y - 3.2, x + 3.2, y + 3.2)
    infill = [xs[0] + paper(1500 * k, scale) for k in (1, 2, 3)] + [xs[1] + paper(1500 * k, scale) for k in (1, 2)]
    for x in infill:
        c.line((x, y1), (x, y2), 1.2)

    for x0, x1 in zip(xs, xs[1:], strict=False):
        c.text((x0 + x1) / 2, y2 - 4, MAIN_BEAM, 6.5, "center")
        c.text((x0 + x1) / 2, y1 - 4, MAIN_BEAM, 6.5, "center")
    mid_y = (y1 + y2) / 2
    for x in xs:
        c.text(x - 4, mid_y, END_BEAM, 6.5, "center", angle=90)
    for x in (infill[1], infill[4]):
        c.text(x - 4, mid_y, INFILL_BEAM, 6.5, "center", angle=90)
    c.text((infill[2] + xs[1]) / 2, mid_y + 30, "GRATING", 6.5, "center")
    c.text((infill[2] + xs[1]) / 2, mid_y + 38, "SPAN", 6.5, "center")

    for x0, x1, bay in zip(xs, xs[1:], BAYS, strict=False):
        c.dimension((x0, y2), (x1, y2), 40, str(bay))
    c.dimension((xs[0], y2), (xs[-1], y2), 62, str(sum(BAYS)))
    c.dimension((xs[0], y1), (xs[0], y2), 50, str(WIDTH))
    c.dimension((xs[0], y1), (infill[0], y1), -22, "1500")
    c.text((xs[0] + infill[0]) / 2 + 16, y1 + 22 + 8, "TYP.", 6.5)

    # section marks: where each elevation on S-201 is cut, and the details on S-301
    c.callout((xs[-1] + 70, mid_y), "1", "S-201")
    c.leader((xs[-1] + 57, mid_y), (xs[-1] + 8, mid_y))
    c.callout((xs[1], y1 + 62), "2", "S-201")
    c.leader((xs[1], y1 + 49), (xs[1], y1 + 8))
    c.callout((xs[-1] + 70, y2 - 40), "1", "S-301")
    c.leader((xs[-1] + 59, y2 - 33), (xs[-1] + 5, y2 - 4))
    c.callout((xs[1] + 42, y2 + 60), "2", "S-301")
    c.leader((xs[1] + 35, y2 + 49), (xs[1] + 4, y2 + 5))

    c.view_title(xs[0] + 190, y1 + 120, "T.O. STEEL FRAMING PLAN", "1:50", "1", "S-101")

    c.notes(
        910,
        60,
        "PLAN NOTES:",
        [
            "TOP OF STEEL IS AT EL. 3600 UNLESS NOTED OTHERWISE.",
            f"INFILL BEAMS ARE {INFILL_BEAM} AT 1500 CENTRES.",
            "GRATING SPANS BETWEEN INFILL BEAMS. FASTEN WITH SADDLE CLIPS AT 600 CENTRES.",
            "COLUMNS ARE CENTRED ON THE GRID LINES. SEE S-401 FOR THE COLUMN SCHEDULE.",
            "GUARDRAIL ON ALL FOUR SIDES. SEE DWG S-501.",
        ],
        width=270,
    )


# ---- S-201 -----------------------------------------------------------------------------------


def elevations(c: Canvas) -> None:
    frame(c, "S-201", "1:50", date="2030-05-08")
    scale = 50
    base = 480.0  # top of the existing slab
    top = base - paper(TOP_OF_STEEL, scale)
    guard = base - paper(TOP_OF_GUARD, scale)

    # view 1 (left): the end frame on grid C, looking along the platform
    x1 = 100.0
    x2 = x1 + paper(WIDTH, scale)
    c.line((x1 - 40, base), (x2 + 40, base), MEDIUM)
    for x, name in ((x1, "1"), (x2, "2")):
        c.grid_line((x, guard - 28), (x, base + 22))
        c.grid_bubble((x, guard - 40), name)
        c.line((x, base), (x, top), HEAVY)
        c.line((x, top), (x, guard), MEDIUM)
        c.text(x - 4, (base + top) / 2, COLUMN, 6.5, "center", angle=90)
    c.line((x1, top), (x2, top), HEAVY)
    c.line((x1, guard), (x2, guard), MEDIUM)
    c.text((x1 + x2) / 2, top - 4, END_BEAM, 6.5, "center")
    c.dimension((x1, base), (x2, base), -34, str(WIDTH))
    c.dimension((x2, base), (x2, top), -36, str(TOP_OF_STEEL))
    c.dimension((x2, top), (x2, guard), -36, str(TOP_OF_GUARD - TOP_OF_STEEL))
    c.dimension((x2, base), (x2, guard), -58, str(TOP_OF_GUARD))
    c.callout((x1 - 50, base - 30), "1", "S-301")
    c.leader((x1 - 39, base - 23), (x1 - 5, base - 3))
    c.view_title(x1 + 110, base + 96, "ELEVATION ON GRID C", "1:50", "1", "S-201")

    # view 2 (right): the braced frame on grid 1
    xa = 470.0
    xs = [xa, xa + paper(BAYS[0], scale), xa + paper(sum(BAYS), scale)]
    c.line((xs[0] - 40, base), (xs[-1] + 40, base), MEDIUM)
    for x, name in zip(xs, "ABC", strict=True):
        c.grid_line((x, guard - 28), (x, base + 22))
        c.grid_bubble((x, guard - 40), name)
        c.line((x, base), (x, top), HEAVY)
        c.line((x, top), (x, guard), MEDIUM)
        c.text(x - 4, (base + top) / 2, COLUMN, 6.5, "center", angle=90)
    c.line((xs[0], top), (xs[-1], top), HEAVY)
    c.line((xs[0], guard), (xs[-1], guard), MEDIUM)
    for x0, x1b in zip(xs, xs[1:], strict=False):
        c.text((x0 + x1b) / 2, top - 4, MAIN_BEAM, 6.5, "center")
    c.line((xs[0], base), (xs[1], top), 1.2)  # the brace
    rise = math.radians(BRACE_ANGLE)
    mid = ((xs[0] + xs[1]) / 2, (base + top) / 2)
    c.text(mid[0] - 4 * math.sin(rise), mid[1] - 4 * math.cos(rise), BRACE, 6.5, "center", angle=BRACE_ANGLE)
    c.text(xs[0] + 40, base - 9, f"{BRACE_ANGLE}°", 6.5)
    for x0, x1b, bay in zip(xs, xs[1:], BAYS, strict=False):
        c.dimension((x0, base), (x1b, base), -34, str(bay))
    c.dimension((xs[0], base), (xs[-1], base), -56, str(sum(BAYS)))
    marker_x = xs[-1] + 84
    for level, name in ((TOP_OF_GUARD, "T.O. GUARD"), (TOP_OF_STEEL, "T.O. STEEL"), (0, "T.O. SLAB")):
        c.level_marker(marker_x, base - paper(level, scale), name, str(level), run=30)
    c.callout((xs[1] + 60, top + 44), "2", "S-301")
    c.leader((xs[1] + 50, top + 36), (xs[1] + 5, top + 5))
    c.callout((xs[0] + 96, base - 22), "3", "S-301")
    c.leader((xs[0] + 83, base - 22), (xs[0] + 14, base - 4))
    c.view_title(xs[0] + 180, base + 96, "ELEVATION ON GRID 1", "1:50", "2", "S-201")


# ---- S-301 -----------------------------------------------------------------------------------


def details(c: Canvas) -> None:
    frame(c, "S-301", "1:10", revisions=(*ISSUES, REVISED), date="2030-06-19", drawn="HZK")
    scale = 10

    # detail 1: column base plate, plan
    cx, cy = 210.0, 300.0
    half = paper(350, scale) / 2
    c.rect(cx - half, cy - half, cx + half, cy + half, MEDIUM)
    hss = paper(152, scale) / 2
    wall = paper(9.5, scale)
    c.rect(cx - hss, cy - hss, cx + hss, cy + hss, HEAVY)
    c.rect(cx - hss + wall, cy - hss + wall, cx + hss - wall, cy + hss - wall, MEDIUM)
    rod = paper(125, scale)
    for sx in (-1, 1):
        for sy in (-1, 1):
            c.circle((cx + sx * rod, cy + sy * rod), paper(13, scale), MEDIUM)
    edge = paper(50, scale)
    xs = [cx - half, cx - half + edge, cx + half - edge, cx + half]
    for x0, x1, value in zip(xs, xs[1:], (50, 250, 50), strict=False):
        c.dimension((x0, cy - half), (x1, cy - half), 26, str(value))
    c.dimension((xs[0], cy - half), (xs[-1], cy - half), 46, "350")
    ys = [cy + half, cy + half - edge, cy - half + edge, cy - half]
    for y0, y1, value in zip(ys, ys[1:], (50, 250, 50), strict=False):
        c.dimension((cx - half, y0), (cx - half, y1), 26, str(value))
    c.dimension((cx - half, ys[0]), (cx - half, ys[-1]), 46, "350")
    c.leader((cx + half - 12, cy + half - 6), (cx + half + 30, cy + half + 26))
    c.text(cx + half + 32, cy + half + 29, BASE_PLATE, 6.5)
    c.leader((cx + rod + 3, cy - rod - 3), (cx + half + 30, cy - half - 4))
    c.text(cx + half + 32, cy - half - 2, "Ø20 THREADED ROD ANCHORS, 4 REQUIRED", 6.5)
    c.leader((cx - rod - 3, cy + rod + 3), (cx - half - 14, cy + half + 20))
    c.text(cx - half - 16, cy + half + 28, "Ø26", 6.5, "right")
    c.leader((cx + hss, cy), (cx + half + 30, cy + 4))
    c.text(cx + half + 32, cy + 6, COLUMN, 6.5)
    c.fillet_weld((cx + hss, cy + 14), (cx + half + 30, cy + 44), "6", typical=True)
    c.text(cx - half, cy + half + 64, "25 NON-SHRINK GROUT UNDER PLATE", 6.5)
    c.view_title(cx - 40, 560, "COLUMN BASE PLATE", "1:10", "1", "S-301")

    # detail 2: beam to column shear tab, elevation
    fx, by = 600.0, 250.0  # face of the column, top of the beam
    depth = paper(310, scale)
    c.line((fx, by - 60), (fx, by + depth + 70), HEAVY)
    c.line((fx - 2 * hss, by - 60), (fx - 2 * hss, by + depth + 70), HEAVY)
    gap = paper(12, scale)
    c.line((fx + gap, by), (fx + 170, by), HEAVY)
    c.line((fx + gap, by + depth), (fx + 170, by + depth), HEAVY)
    c.line((fx + gap, by), (fx + gap, by + depth), MEDIUM)
    tab_w, tab_h = paper(100, scale), paper(230, scale)
    ty = by + (depth - tab_h) / 2
    c.rect(fx, ty, fx + tab_w, ty + tab_h, MEDIUM)
    bolt_x = fx + paper(60, scale)
    rows = [ty + paper(v, scale) for v in (40, 115, 190)]
    for y in rows:
        c.circle((bolt_x, y), paper(11, scale), MEDIUM)
    dim_x = fx + 170 + 14
    ys = [ty + tab_h, rows[2], rows[1], rows[0], ty]
    for y0, y1, value in zip(ys, ys[1:], (40, 75, 75, 40), strict=False):
        c.dimension((dim_x, y0), (dim_x, y1), -18, str(value))
    c.dimension((dim_x, ys[0]), (dim_x, ys[-1]), -40, "230")
    c.text(fx + 110, by - 5, MAIN_BEAM, 6.5, "center")
    c.text(fx - hss - 4, by + depth + 30, COLUMN, 6.5, "center", angle=90)
    c.leader((fx + tab_w - 4, ty + tab_h - 4), (fx + 80, by + depth + 36))
    c.text(fx + 82, by + depth + 39, SHEAR_TAB, 6.5)
    c.leader((bolt_x + 3, rows[0] - 2), (fx + 80, by - 30))
    c.text(fx + 82, by - 28, "3 - M20 A325M BOLTS IN 22 DIA. HOLES", 6.5)
    c.fillet_weld((fx, ty + tab_h - 10), (fx - 110, by + depth + 50), "6", both_sides=True)
    c.view_title(fx - 10, 560, "BEAM TO COLUMN SHEAR TAB", "1:10", "2", "S-301")

    # detail 3: brace gusset at the column base, elevation
    gx, gy = 960.0, 400.0  # face of the column at the top of the base plate
    c.line((gx, gy - 200), (gx, gy), HEAVY)
    c.line((gx - 2 * hss, gy - 200), (gx - 2 * hss, gy), HEAVY)
    c.line((gx - 2 * hss - 30, gy), (gx + 190, gy), HEAVY)
    plate_l, plate_h = paper(300, scale), paper(260, scale)
    c.polyline(
        [(gx, gy), (gx + plate_l, gy), (gx + plate_l, gy - 26), (gx + 30, gy - plate_h), (gx, gy - plate_h)],
        MEDIUM,
        close=True,
    )
    rise = math.radians(BRACE_ANGLE)
    ux, uy = math.cos(rise), -math.sin(rise)  # along the brace, from the work point at the column base
    px, py = -uy, ux  # across it
    half_leg = paper(102, scale) / 2
    for side in (-1, 1):
        a = (gx + 70 * ux + side * half_leg * px, gy + 70 * uy + side * half_leg * py)
        c.line(a, (a[0] + 190 * ux, a[1] + 190 * uy), 1.2)
    c.line((gx, gy), (gx + 280 * ux, gy + 280 * uy), dashes="[9 2 2 2] 0")
    label_at = (gx + 200 * ux - (half_leg + 4) * px, gy + 200 * uy - (half_leg + 4) * py)
    c.text(label_at[0], label_at[1], BRACE, 6.5, "center", angle=BRACE_ANGLE)
    c.text(gx + plate_l + 24, gy - 8, f"{BRACE_ANGLE}°", 6.5)
    c.dimension((gx, gy), (gx + plate_l, gy), -24, "300")
    c.leader((gx + 12, gy - plate_h + 10), (gx + 40, gy - plate_h - 36))
    c.text(gx + 42, gy - plate_h - 38, "PL10", 6.5)
    c.text(gx + 62, gy - plate_h - 38, "GUSSET", 6.5)
    c.text(gx + plate_l + 8, gy - 36, "R25", 6.5)
    c.fillet_weld((gx + 60, gy), (gx + 96, gy + 62), "6", both_sides=True, typical=True)
    c.view_title(gx - 10, 560, "BRACE GUSSET AT COLUMN BASE", "1:10", "3", "S-301", length=230)


# ---- S-401 -----------------------------------------------------------------------------------


def schedule_and_isometric(c: Canvas) -> None:
    frame(c, "S-401", "AS NOTED")
    c.text(60, 70, "COLUMN SCHEDULE", 10, font=BOLD)
    rows = [("GRID", "MARK", "SIZE", "BASE PLATE", "ANCHOR RODS", "T.O. STEEL")]
    for grid in ("A-1", "A-2", "B-1", "B-2", "C-1", "C-2"):
        braced = grid in ("A-1", "B-1")
        rows.append((grid, "C2" if braced else "C1", COLUMN, BASE_PLATE, "4 - Ø20", str(TOP_OF_STEEL)))
    below = c.table(60, 80, (50, 50, 110, 100, 80, 70), rows)
    c.notes(
        60,
        below + 30,
        "SCHEDULE NOTES:",
        [
            "C2 COLUMNS CARRY THE BRACE GUSSET. SEE DETAIL 3/S-301.",
            "ANCHOR RODS ARE CAST INTO DRILLED HOLES WITH ADHESIVE. EMBEDMENT 200 MINIMUM.",
        ],
        width=420,
    )

    # isometric: a cabinet projection of the frame, not to scale
    ox, oy, k = 700.0, 520.0, 0.036
    depth = (0.5 * math.cos(math.radians(35)), -0.5 * math.sin(math.radians(35)))

    def iso(x: float, y: float, z: float) -> tuple[float, float]:
        return (ox + k * (x + depth[0] * y), oy + k * (depth[1] * y - z))

    xs = (0, BAYS[0], sum(BAYS))
    for x in xs:
        for y in (0, WIDTH):
            c.line(iso(x, y, 0), iso(x, y, TOP_OF_STEEL), HEAVY)
            c.line(iso(x, y, TOP_OF_STEEL), iso(x, y, TOP_OF_GUARD), MEDIUM)
        c.line(iso(x, 0, TOP_OF_STEEL), iso(x, WIDTH, TOP_OF_STEEL), HEAVY)
    for y in (0, WIDTH):
        c.line(iso(0, y, TOP_OF_STEEL), iso(xs[-1], y, TOP_OF_STEEL), HEAVY)
        c.line(iso(0, y, TOP_OF_GUARD), iso(xs[-1], y, TOP_OF_GUARD), MEDIUM)
    for x in (0, xs[-1]):
        c.line(iso(x, 0, TOP_OF_GUARD), iso(x, WIDTH, TOP_OF_GUARD), MEDIUM)
    for x in (1500, 3000, 4500, 7500, 9000):
        c.line(iso(x, 0, TOP_OF_STEEL), iso(x, WIDTH, TOP_OF_STEEL), MEDIUM)
    c.line(iso(0, 0, 0), iso(BAYS[0], 0, TOP_OF_STEEL), 1.2)
    c.view_title(ox + 60, oy + 60, "ISOMETRIC VIEW", "N.T.S.", "1", "S-401")


# ---- the files -------------------------------------------------------------------------------


def build_set() -> pymupdf.Document:
    doc = pymupdf.open()
    for draw in (general_notes, framing_plan, elevations):
        draw(new_sheet(doc))
    flat = pymupdf.open()
    details(new_sheet(flat))
    plot_rotated(doc, flat)
    schedule_and_isometric(new_sheet(doc))
    return doc


def build_scan() -> pymupdf.Document:
    flat = pymupdf.open()
    framing_plan(new_sheet(flat))
    return rasterise(flat, 0)


def main() -> None:
    save(build_set(), str(HERE / "access_platform_set.pdf"), "Conveyor access platform: synthetic structural set")
    save(build_scan(), str(HERE / "access_platform_scan.pdf"), "Conveyor access platform: framing plan as a scan")
    print("wrote", ", ".join(p.name for p in sorted(HERE.glob("*.pdf"))))


if __name__ == "__main__":
    main()
