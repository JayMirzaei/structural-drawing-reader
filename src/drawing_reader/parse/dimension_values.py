"""Dimension values: turning the text of a dimension into millimetres.

A bare number is millimetres unless the sheet says otherwise; imperial lengths are written in feet and
inches; a number may carry its own unit, or be a radius or a diameter.
"""

from __future__ import annotations

import re

RE_NUMBER = re.compile(r"^-?\d{1,6}(?:\.\d+)?$")


# Dimension values. Conventions: a bare number is millimetres unless the sheet says otherwise ("ALL DIMENSIONS ARE IN
# INCHES"); imperial lengths are written feet-and-inches ("3'-6\"", "12'-0 1/2\"", "20'8 3/4\"", "6\"", "3'") with
# prime/double-prime marks that OCR renders as ′ ″ ’ ”; a number may carry its unit ("150mm", "1.5 m"); a radius is
# "R50", a diameter "Ø25".
FOOT_MARK = r"['′’]"


INCH_MARK = r"[\"″”]"


RE_DIM_FTIN = re.compile(
    rf"^(?:(?P<ft>\d{{1,3}}){FOOT_MARK}\s?-?\s?)?(?:(?P<in>\d{{1,2}})(?:\s?(?P<num>\d{{1,2}})/(?P<den>\d{{1,2}}))?\s?{INCH_MARK}?)?$"
)


RE_DIM_UNIT = re.compile(r"^(?P<v>\d+(?:\.\d+)?)\s?(?P<u>mm|cm|m)$", re.I)


RE_DIM_RADIUS = re.compile(r"^R\s?(?P<v>\d+(?:\.\d+)?)$")


RE_DIM_DIAMETER = re.compile(r"^[Øø⌀]\s?(?P<v>\d+(?:\.\d+)?)$")


RE_DIM_UNITS_NOTE = re.compile(
    r"DIMENSIONS?\s+(?:ARE\s+)?(?:SHOWN\s+)?(?:IN\s+)?(?P<u>MILLIMET(?:RE|ER)S?|MM|INCHES|FEET|METRES?|METERS?)", re.I
)


# words that follow a dimension value and belong to it ("3000 TYP", "6000 CLR", "250 O.C.", "64 mm"), not to a note
RE_DIM_QUALIFIER = re.compile(
    r"^(?:TYP|TYPICAL|CLR|CLEAR|MIN|MAX|EQ|EQL|EQUAL|EA|EACH|OC|O\.C|NOM|REF|SIM|SIMILAR|UNO|U\.N\.O|MM|CM|M|IN|FT|SPA|SPACES|BTWN|VARIES|VAR|TYP\.)\b",
    re.I,
)


RE_FTIN_BADMARK = re.compile(
    rf"^(\d{{1,3}}{FOOT_MARK}\s?-?\s?\d{{1,2}}(?:\s?\d{{1,2}}/\d{{1,2}})?)(?:[*°¨]|['′’‘]{{2}})$"
)


def dimension_value(text: str, default_unit: str = "mm"):
    """(value in mm, unit shown, kind) of a dimension text, or None. kind: linear | radius | diameter."""
    t = text.strip()
    if not t:
        return None
    # OCR reads the inch mark of 2'-8" as * or ° or '' -- only after a feet part, so 45° stays an angle
    bad = RE_FTIN_BADMARK.match(t)
    if bad:
        t = bad.group(1) + '"'
    if RE_NUMBER.match(t):
        if re.fullmatch(r"0\d+", t):
            # 049, 054: a detail / sheet reference or a title-block figure -- a length is not written with a leading
            # zero
            return None
        if "." in t and len(t.split(".")[1]) >= 3:
            return None  # 249.256: an elevation in metres, not a dimension
        return (
            float(t) * {"mm": 1.0, "in": 25.4, "ft": 304.8, "m": 1000.0}.get(default_unit, 1.0),
            default_unit,
            "linear",
        )
    m = RE_DIM_UNIT.match(t)
    if m:
        return (
            float(m.group("v")) * {"mm": 1.0, "cm": 10.0, "m": 1000.0}[m.group("u").lower()],
            m.group("u").lower(),
            "linear",
        )
    m = RE_DIM_RADIUS.match(t) or RE_DIM_DIAMETER.match(t)
    if m:
        return (float(m.group("v")), default_unit, "radius" if t[0] == "R" else "diameter")
    m = RE_DIM_FTIN.match(t)
    if m and (m.group("ft") or re.search(INCH_MARK, t)):
        inches = (
            int(m.group("ft") or 0) * 12
            + int(m.group("in") or 0)
            + (int(m.group("num")) / int(m.group("den")) if m.group("num") and int(m.group("den")) else 0)
        )
        return (inches * 25.4, "ft-in", "linear") if inches > 0 else None
    return None
