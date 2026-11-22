"""Text conventions of general notes: item markers, headings, load-table labels.

Used by the notes parser to split paragraphs into numbered items and to tell a note from a title
line, a field label or a path.
"""

from __future__ import annotations

import re

RE_ITEM_NO = re.compile(r"^(\d{1,2})[.)]?$")


RE_BULLET = re.compile(r"^[•·\-–]\s*(.*)$")


# Note items that start with the marker glued to the text, as many CAD exports print them: "-THE CONTRACTOR SHALL...",
# "11.PROVIDE ...", or a lettered sub-item on its own ("a.", "B)"). A field label ("PROJECT TITLE:", "REV:", "AFE:")
# is never a note heading.
RE_BULLET_GLUED = re.compile(r"^[•·\-–]\s?(?=[A-Z]{2})(.*)$")


RE_ITEM_GLUED = re.compile(r"^(\d{1,2})[.)]\s*(?=[A-Z]{2})(.*)$")


RE_ALPHA_ITEM = re.compile(r"^([A-Za-z])[.)]$")


RE_FIELD_HEADING = re.compile(
    r"^(PROJECT( TITLE| NAME| NO\.?| NUMBER)?|REV(ISION)?|AFE|DATE|DRAWN( BY)?|CHECKED( BY)?|APPROVED( BY)?|CLIENT|JOB( NO\.?)?|"
    r"CONSULTANT|OWNER|ENGINEER|ARCHITECT|SCALE|SHEET( NO\.?| TITLE)?|DWG\.?( NO\.?)?|DRAWING( NO\.?| TITLE)?|TITLE|BY|DESIGNED( BY)?|STATUS|LOCATION|SITE|"
    r"ISSUED FOR\b.*|FOR (CONSTRUCTION|REVIEW|TENDER|PERMIT|APPROVAL))$",
    re.I,
)


# A design-load table states a label ("LIVE LOAD", "DEAD LOAD", "SNOW LOAD") and its value ("1.9
# kPa") as two separate text runs on the same row -- neither RE_PARAM's "NAME = value" convention
# nor RE_PARAM_DOTTED's dotted-leader convention covers this (building load tables are often drawn
# this way). The label must be the run's *entire* text (not e.g. "LOADING CONDITION" or
# "SPECIFIED FLOOR LOADING", a header row above the real label/value rows) and end in the whole
# word "LOAD" (`\bLOAD\b$` excludes "LOADING").
RE_LOAD_LABEL = re.compile(r"^[A-Z][A-Z ]{1,25}\bLOAD$")


# A design-criteria label that is not "<WORD> LOAD": "REFERENCE WIND PRESSURE (q 1/50)", "ULS IMPORTANCE FACTOR",
# "ALLOWABLE BEARING CAPACITY" -- the quantity word plus an optional parenthesised symbol.
RE_CRITERIA_LABEL = re.compile(
    r"^[A-Z][A-Z0-9 /&.-]{2,40}\b(?:LOAD|PRESSURE|FACTOR|CAPACITY)S?(?:\s*\([^()]{1,14}\))?$"
)


RE_LOAD_VALUE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(kPa|kN/m2?|kN|MPa|psf)\b", re.I)


RE_FACTOR_VALUE = re.compile(r"^(\d+(?:\.\d+)?)(?=\s|$|\()")


RE_STRIP_BOILERPLATE = re.compile(
    r"COPYRIGHT|PROPERTY OF|REPRODUC|PERMIT TO PRACTICE|CADD DRAWING|MANUAL REVISION|UNCONTROLLED|PAPER COPIES|"
    r"ELECTRONIC (FILE|DOCUMENT|VERSION)|ALL RIGHTS RESERVED|DO NOT SCALE|\bC[A-Z]{2,3}D?\s+[CD]R[A-Z]{2,5}:|M[A-Z]NUAL\s+RE[VW]|REPRO\w{3,}",
    re.I,
)


RE_NOTE_WORDS = re.compile(
    r"\b(SHALL|MUST|SHOULD|TO BE|ARE|IS|SEE|UNLESS|PROVIDE[D]?|ALL|NOT|REFER|CONFORM|VERIFY|ENSURE|INSTALL|CONTRACTOR|"
    r"U\.?N\.?O\.?|TYP|NOTE:?|MINIMUM|MAXIMUM|REQUIRED|CHECK|COORDINATE|ENGINEER)\b",
    re.I,
)


_ACRONYMS = {"OWSJ", "CSA", "ASTM", "AWS", "UNO", "CIP"}


def heading_case(text: str) -> str:
    """A heading or component name in title case, with acronyms kept in capitals ("HSS COLUMNS" -> "HSS Columns"):
    a short all-capitals word with no vowel, or a known drafting acronym."""

    def word(w: str) -> str:
        letters = re.sub(r"[^A-Za-z]", "", w)
        if letters.isupper() and (letters in _ACRONYMS or (len(letters) <= 4 and not re.search(r"[AEIOUY]", letters))):
            return w
        return w.title()

    return " ".join(word(w) for w in text.split(" "))


def split_numbered_items(number: str, body: str) -> list[tuple[str, str]]:
    """One run block can hold several numbered items printed as one paragraph ("11. PROVIDE ... 12. PROVIDE ..."):
    split where the next number follows the current one (n then n+1), so "2.5 kPa" or a stray "3." mid-sentence does
    not cut an item."""
    if not number.isdigit():
        return [(number, body)]
    out, cur, text = [], int(number), body
    while True:
        m = re.search(r"(?<=[.;:)])\s+(\d{1,2})[.)]\s*(?=[A-Z]{2})", text)
        while m and int(m.group(1)) != cur + 1:
            m = re.compile(r"(?<=[.;:)])\s+(\d{1,2})[.)]\s*(?=[A-Z]{2})").search(text, m.end())
        if not m:
            out.append((str(cur), text))
            return out
        out.append((str(cur), text[: m.start()].strip()))
        cur = int(m.group(1))
        text = text[m.end() :].strip()


def reads_like_strip_note(text: str) -> bool:
    """Whether strip text reads as a note rather than a title line, file path or OCR garble: sentence wording,
    real-looking words."""
    if "\\" in text or re.search(r"\.(dwg|pdf|dgn)\b", text, re.I) or not RE_NOTE_WORDS.search(text):
        return False
    ws = [w for w in re.findall(r"[A-Za-z]{3,}", text)]
    return bool(ws) and sum(bool(re.search(r"[AEIOUYaeiouy]", w)) for w in ws) >= 0.85 * len(ws)
