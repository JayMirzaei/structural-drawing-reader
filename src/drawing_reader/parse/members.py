"""Member designations: steel section names, plates, rods, pipes and joists.

`RE_SECTION` is the strict first reader (metric designations such as W310X67). `parse_extended_member`
is the second pass for imperial sizes with fractions, glued marks and the less common families.
"""

from __future__ import annotations

import re

# `HS`/`HA` are the CSA (Canadian) hollow-section designations ("HS203x203x13", "HA219x9.5"); they
# are stored as family HSS so every member rule treats them like any other hollow section. `count` is the paired-
# angle prefix ("2-L89x89x7.9", "2L127x127x17") -- only in front of an angle, so "2 W310..." text is untouched.
RE_SECTION = re.compile(
    r"^(?:(?P<count>[2-4])\s?-?\s?(?=L\s?\d))?(?P<fam>W|HSS|HS|HA|PL|L|C|MC|WT|HP|S|M|PIPE)\s?"
    r"(?P<dims>\d[\d.]*(?:\s?[Xx×]\s?\d[\d.]*){0,3})(?P<rest>\s.*)?$"
)


RE_ANGLE = re.compile(r"^-?\d{1,3}(?:\.\d+)?\s?°$")


RE_TYP = re.compile(r"^TYP\.?$", re.I)


FAMILY_NAMES = {
    "W": "wide-flange (W-shape)",
    "HSS": "hollow structural section",
    "PL": "plate",
    "L": "angle",
    "C": "channel",
    "MC": "channel (MC)",
    "WT": "tee",
    "HP": "H-pile",
    "S": "S-shape",
    "M": "M-shape",
    "PIPE": "pipe",
    "WWF": "welded wide-flange",
    "FB": "flat bar",
    "ST": "tee (ST)",
    "MT": "tee (MT)",
    "ROD": "round rod",
    "JOIST": "open-web steel joist",
}


# Extended member designations (second pass after RE_SECTION, which stays the strict first reader). Conventions
# handled: imperial sizes with fractions ("HSS4x4x1/4", "L2-1/2x2-1/2x1/4", "L31/2X3X3/8"), a mark or note glued
# to the size ("W410X60MK2", "W360X79FP1", "W250x67(N)"), stray leading/trailing marks ("*W250X49",
# "-PL178x102x12.7", "[W460x113]", "W150x22-"), flat bar (FB), structural tees cut from S/M shapes (ST, MT), tube
# steel (TS), welded wide-flange (WWF); a bare "W250" / "C200" is a depth-only reference (pile and base-plate
# details); round rod ('1-1/2"Ø ROD'), pipe ('168.3 (6") SCH.40') and open-web joist ("16K5").
_DIM = r"(?:\d{1,4}[-\s]\d{1,2}/\d{1,2}|\d{1,3}\d/\d{1,2}|\d{1,2}/\d{1,2}|\d*\.?\d+)"


RE_MEMBER_EXT = re.compile(
    r"^(?:(?P<count>[2-4])\s?-?\s?(?=L\s?\d))?(?P<fam>WWF|HSS|HS|HA|PL|FB|WT|MC|ST|MT|TS|HP|W|L|C|S|M)\s?-?\s?"
    r"(?P<dims>" + _DIM + r"(?:\s?[Xx]\s?" + _DIM + r"){0,3})(?P<rest>(?![\d.]).*)$"
)


_STD_DEPTHS = {
    "W": {100, 130, 150, 200, 250, 310, 360, 410, 460, 530, 610, 690, 760, 840, 920, 1000, 1100},
    "C": {75, 100, 130, 150, 180, 200, 230, 250, 310, 380},
}


RE_MEMBER_DEPTH = re.compile(r"^(?P<fam>W|C)(?P<depth>\d{3,4})$")


RE_ROD = re.compile(
    r"^(?P<size>\d[\d./\- ]*?)\s*[\"”*°]?\s*[ØøΦ⌀]\s*(?:THREADED\s+|THRD\s+)?ROD\b(?P<rest>.*)$"
    r"|^[ØøΦ⌀]\s?(?P<size2>\d+(?:\.\d+)?)\s?(?:mm)?\s*(?:THREADED\s+|THRD\s+)?ROD\b(?P<rest2>.*)$",
    re.I,
)


RE_PIPE = re.compile(
    r"^(?:PIPE\s*)?(?P<size>\d[\d./\-]*)\s*(?:\(\s*\d[\d./\-]*\s*[\"”*°]?\s*\)\s*)?[\"”*°]?\s*(?:PIPE\s+)?"
    r"(?P<sch>SCH\.?\s?\d+S?|STD|XXS|XS)\b(?P<rest>.*)$",
    re.I,
)


RE_JOIST = re.compile(r"^(?P<depth>\d{2})\s?(?P<series>K|LH|DLH)\s?(?P<num>\d{1,2})$")


def _canon_dims(dims: str) -> str:
    """'31/2 x 3 x 3/8' -> '3-1/2X3X3/8': one spelling per size, so equal designations compare equal."""
    out = []
    for d in re.split(r"\s?[Xx]\s?", dims.strip()):
        d = d.strip()
        m = re.fullmatch(r"(\d{1,3})(\d/\d{1,2})", d)  # glued mixed number "31/2" (a whole part then a fraction)
        if m and "/" in d and len(d.split("/")[0]) >= 2:
            d = f"{m.group(1)}-{m.group(2)}"
        out.append(re.sub(r"\s", "-", d))
    return "X".join(out)


def _mixed_number(text: str) -> float:
    """Value of a size written as a decimal, a fraction or a mixed number: '12.7', '3/8', '3-1/2' (= 3.5).
    Raises ValueError for anything else and ZeroDivisionError for a zero denominator."""
    if "/" not in text:
        return float(text)
    total = 0.0
    for term in text.split("-"):
        num, _, den = term.partition("/")
        total += _whole(num) / _whole(den) if den or "/" in term else _whole(num)
    return total


def _whole(text: str) -> int:
    """A whole number as drawn in a fraction; digits only, and no leading zero ("08") unless it is zero itself."""
    if not text.isdigit() or (text[0] == "0" and text.strip("0")):
        raise ValueError(text)
    return int(text)


def parse_extended_member(t: str):
    """(family, section, attrs) for a member designation RE_SECTION does not read, else None."""
    t = t.replace("×", "X").strip()
    t = re.sub(r"^[\s*\-\[(•]+", "", t)
    m = RE_MEMBER_DEPTH.match(t)
    if m and int(m.group("depth")) in _STD_DEPTHS[m.group("fam")]:
        return m.group("fam"), t, dict(partial=True, depth=m.group("depth"))
    m = RE_MEMBER_EXT.match(t)
    if m:
        fam, dims, rest = m.group("fam"), _canon_dims(m.group("dims")), m.group("rest").strip()
        many = "X" in dims.upper()
        if not many:
            # a lone number after these letters is a mark or a thickness (RE_SECTION reads "PL 10"), not a size
            return None
        attrs = {}
        if fam == "PL":
            parts = dims.split("X")
            try:
                nums = [_mixed_number(p) for p in parts]
                thin = nums.index(min(nums))
                attrs["thickness"] = parts[thin]
                attrs["plan"] = "X".join(parts[:thin] + parts[thin + 1 :])
            except (ValueError, ZeroDivisionError):
                return None
        if fam == "TS" or fam in ("HS", "HA"):
            attrs["designation_prefix"] = fam
            fam = "HSS"
        if m.group("count"):
            attrs["count"] = int(m.group("count"))
        if rest:
            attrs["tail"] = rest[:40]
            mk = re.match(r"^([A-Z]{1,3}\d{1,2})", rest)
            if mk:
                attrs["mark"] = mk.group(1)
        attrs["units"] = "imperial" if "/" in dims else None
        return fam, (m.group("fam") + dims).replace(" ", ""), {k: v for k, v in attrs.items() if v is not None}
    m = RE_ROD.match(t)
    if m:
        size = (m.group("size") or m.group("size2")).strip(" -")
        return "ROD", f"ROD{size}".replace(" ", ""), dict(tail=(m.group("rest") or m.group("rest2") or "").strip()[:40])
    m = RE_PIPE.match(t)
    if m and not re.match(r"^\s*[A-Za-z]{3,}", m.group("rest") or ""):
        return (
            "PIPE",
            f"PIPE{m.group('size')} {re.sub(r'[ .]', '', m.group('sch').upper())}",
            dict(tail=(m.group("rest") or "").strip()[:40]),
        )
    m = RE_JOIST.match(t)
    if m:
        return "JOIST", f"{m.group('depth')}{m.group('series')}{m.group('num')}", {}
    return None
