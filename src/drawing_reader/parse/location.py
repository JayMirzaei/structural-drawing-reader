"""Project location: where a title block says the site is.

Recognises a labelled field, a street address, a "City, Province" line and a legal land description,
and picks the set's location from the per-sheet finds.
"""

from __future__ import annotations

import re
from collections import Counter

from drawing_reader.parse.regions import CODES_PATTERN, COUNTRY_NAMES, NAMES_PATTERN, POSTAL_PATTERN
from drawing_reader.schema import Fact, Index

# Project location. Convention: a title block states where the site is as a labelled field ("LOCATION: ..."), a street
# address ("8120 41 STREET", "77 EXAMPLE RD NW"), a "City, Region" line, or (rural and industrial sites in western
# Canada) a legal land description ("03-15-022-11W2"). The consultant's own address can sit in the same block; the
# facts say which kind of text they came from so an answer can show it and be checked against the sheet.
#
# Regions come from the table in `regions.py` (every Canadian province and territory, every US state). A region
# written out ("MANITOBA") counts wherever it follows a city. A two-letter code is weaker evidence: "OR", "IN", "ON",
# "NS", "GA" and "FL" are also words and drafting abbreviations, so after "City," a code counts only when it closes
# the line or a postal code or the country follows, and without the comma only when a postal code follows.


RE_LOC_ADDRESS = re.compile(
    r"\b\d{2,6}\s*-?\s*(?:\d{1,3}(?:ST|ND|RD|TH)?\s)?[A-Za-z0-9.' ]{2,25}\s"
    # not "PL"/"WAY"/"CT": plates and "EACH WAY"
    r"(?:AVE(?:NUE)?|ST(?:REET)?|RD|ROAD|DR(?:IVE)?|BLVD|BOULEVARD|HWY|HIGHWAY|CRES(?:CENT)?|TRAIL|PLACE|COURT|LANE)\b\.?"
    r"(?:\s?(?:NW|NE|SW|SE|N|S|E|W)\b)?",
    re.I,
)


_COUNTRY = "|".join(re.escape(name) for name in COUNTRY_NAMES)
_REGION_NAME = rf"(?i:{NAMES_PATTERN})\b(?![A-Za-z])"
_CODE_CLOSING = rf"(?:{CODES_PATTERN})\b(?=\s*(?:$|[,.]?\s*(?:{POSTAL_PATTERN}|(?:{_COUNTRY})(?![A-Za-z]))))"
_CODE_BEFORE_POSTAL = rf"(?:{CODES_PATTERN})\b(?=[,.]?\s*{POSTAL_PATTERN})"


RE_LOC_CITY_PROV = re.compile(
    rf"\b([A-Z][A-Za-z.' -]{{2,24}}?)\s*,\s*({_REGION_NAME}|{_CODE_CLOSING})"
    rf"|\b([A-Z][a-z]{{3,20}}|[A-Z]{{4,20}})\s+({_REGION_NAME}|{_CODE_BEFORE_POSTAL})"
)


_RE_POSTAL_NEXT = re.compile(rf"[,.]?\s*{POSTAL_PATTERN}")


_NOT_A_CITY = {
    "SHALL",
    "APPLICABLE",
    "COMPLEX",
    "CHECK",
    "ALL",
    "THE",
    "FOR",
    "AND",
    "DATE",
    "NOTE",
    "NOTES",
    "SEE",
    "TO",
    "BE",
    "OF",
    "IN",
    "ON",
    "OR",
    "AT",
    "BY",
    "WITH",
    "THIS",
    "THAT",
    "FROM",
    "ALSO",
    "WITHIN",
    "THROUGHOUT",
}


def plausible_city(c: str, postal_code_follows: bool = False) -> bool:
    """Words of a "City, Region" candidate that are English filler or drawing terms ("SHALL, BC" from "...SHALL
    BC...") are not a city. A one-word name of three or four letters is almost always a scan's junk ("AWS, QC",
    "TYP, BC"); real towns that short exist, so one is accepted when a postal code follows the region."""
    words = c.replace(".", " ").split()
    if len(words) == 1 and len(words[0]) < 5 and not postal_code_follows:
        return False
    return (
        1 <= len(words) <= 4 and not any(w.upper() in _NOT_A_CITY for w in words) and not any(ch.isdigit() for ch in c)
    )


def find_city_region(text: str) -> tuple[str, str] | None:
    """(city, region) of the first "City, Region" in `text` that reads as a place, else None."""
    m = RE_LOC_CITY_PROV.search(text)
    if m is None:
        return None
    city, region = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    if not plausible_city(city, bool(_RE_POSTAL_NEXT.match(text, m.end()))):
        return None
    return city.strip(), region


RE_LOC_LEGAL = re.compile(
    r"\b(?:NE|NW|SE|SW|LSD\s?\d{1,2}|\d{1,2})\s*-\s*\d{1,2}\s*-\s*\d{1,3}\s*-\s*\d{1,2}\s*W\s?\d\b", re.I
)


RE_LOC_LABEL = re.compile(
    r"^(?:PROJECT\s+|SITE\s+)?(?:LOCATION|ADDRESS|SITE)\s*[:#]\s*(.*)$|^(?:PROJECT\s+|SITE\s+)(?:LOCATION|ADDRESS)\s*$",
    re.I,
)


_LOC_PRIORITY = ("label", "address", "legal_land", "city_province")


def project_location(idx: Index) -> str:
    """The set's location: the text found on the most sheets (a one-off match is noise; the project's own location
    repeats on every sheet), then the more specific kind (label > address > legal land > city), then the bigger text
    (a project heading is larger than a consultant's letterhead). The consultant's own address can still win -- the
    answer says where it was read so it can be checked."""
    facts = [f for f in idx.by_kind("titleblock") if f.attrs.get("field") == "Location"]
    groups: dict[str, list[Fact]] = {}
    for f in facts:
        groups.setdefault(re.sub(r"[^A-Z0-9]", "", f.value.upper()), []).append(f)
    if not groups:
        return ""
    n = len(idx.sheets)

    def score(fs: list[Fact]):
        kind = min(_LOC_PRIORITY.index(f.attrs.get("loc_kind", "city_province")) for f in fs)
        full = any("," in f.value and f.attrs.get("loc_kind") == "address" for f in fs)
        return (
            len({f.sheet for f in fs}) >= max(2, 0.5 * n),
            -kind + (0.5 if full else 0),
            max(f.attrs.get("size", 0) for f in fs),
            len({f.sheet for f in fs}),
        )

    best = max(groups.values(), key=score)
    return Counter(f.value for f in best).most_common(1)[0][0]
