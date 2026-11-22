"""Title-block field labels: the keys a 'Key  Value' pair can carry, and how to recognise a label.

Labels repeat on every sheet and are often set at the same size as their values, so the title and
number readers need to know a label when they see one, including a scan's misspelling of it.
"""

from __future__ import annotations

import difflib
import re

from drawing_reader.parse.revision_text import REV_TABLE_HEADER_WORDS

TITLEBLOCK_KEYS = [
    "PROJECT NUMBER",
    "PROJECT NO",
    "JOB NO",
    "JOB NUMBER",
    "DATE",
    "DRAWN BY",
    "DRAWN",
    "CHECKED BY",
    "CHECKED",
    "DESIGNED BY",
    "APPROVED BY",
    "SCALE",
    "CLIENT",
    "REV",
    "SHEET",
    "SHEET NUMBER",
    "SHEET TITLE",
    "DRAWING NO",
    "DWG NO",
]


# A label spelling out "#" for "number" ("PROJ #") that means the
# same field as an existing TITLEBLOCK_KEYS entry -- mapped after the "#"/"." stripping below.
TITLEBLOCK_KEY_ALIASES = {
    "PROJ": "PROJECT NO",
    "TITLE": "SHEET TITLE",
    "DRAWING TITLE": "SHEET TITLE",
    "DWG TITLE": "SHEET TITLE",
    "DOCUMENT NAME": "SHEET TITLE",
    "DOCUMENT TITLE": "SHEET TITLE",
    "DRAWING NAME": "SHEET TITLE",
}


NON_VALUE_WORDS = set(TITLEBLOCK_KEYS) | REV_TABLE_HEADER_WORDS


# Template placeholder text left in an unfilled title-block cell ("Checker", "Author", "Issue Date",
# "Project Number", or a bare "-"): a label-shaped or punctuation-only run is
# not a field's value, and answering with it ("Checked By: Checker") is a confidently wrong answer.
PLACEHOLDER_VALUES = {
    "AUTHOR",
    "CHECKER",
    "DESIGNER",
    "APPROVER",
    "ISSUE DATE",
    "PROJECT NUMBER",
    "REVISION",
    "N/A",
    "NA",
}


SHEET_ID_KEYS = {"SHEET", "SHEET NUMBER", "DRAWING NO", "DWG NO"}


_LABEL_FORMS = {re.sub(r"[^A-Z]", "", k) for k in TITLEBLOCK_KEYS + list(TITLEBLOCK_KEY_ALIASES)} | {
    "CLIENT",
    "PROJECT",
    "PROJECTTITLE",
    "TITLE",
    "DRAWINGTITLE",
    "DRAWINGNO",
    "DRAWINGNUMBER",
    "SHEETNO",
    "SHEETTITLE",
    "CONSULTANT",
    "DESIGNEDBY",
    "DRAWNBY",
    "CHECKEDBY",
    "APPROVEDBY",
    "REVISION",
    "REVISIONS",
    "SCALE",
    "DATE",
    "JOBNO",
    "PROJECTNO",
    "PROJECTNUMBER",
    "FILENAME",
    "SHEET",
}


RE_PROJNO_INLINE = re.compile(r"^((?:PROJECT|JOB)\s*(?:NUMBER|NO\.?|#))\s*[:#]\s*(.+)$", re.I)


def plausible_project_no(text: str) -> bool:
    """A project / job number: two or more digits, at most two words, and mostly digits and separators ("2031-014",
    "P41207", "31-006", "300.1200.000.041.007")."""
    t = text.strip()
    digits = sum(c.isdigit() for c in t)
    letters = sum(c.isalpha() for c in t)
    return digits >= 2 and len(t.split()) <= 2 and letters <= max(4, digits)


def label_like(text: str) -> bool:
    """A title-block field label as OCR prints it ("DRAWINGNO.", "Project Number:"), which repeats on every sheet like
    the project name does."""
    return re.sub(r"[^A-Z]", "", text.upper()) in _LABEL_FORMS


def is_label_text(text: str) -> bool:
    k = text.rstrip(":.# ").upper()
    return TITLEBLOCK_KEY_ALIASES.get(k, k) in TITLEBLOCK_KEYS


_LABEL_PHRASES = (
    "PLANTAREA",
    "EQUIPNO",
    "FILENAME",
    "APPROVEDBY",
    "DRAWINGNO",
    "DRAWINGNUMBER",
    "REVISIONNO",
    "REVISIONNUMBER",
    "PROJECTNO",
    "PROJECTNUMBER",
    "ISSUEDATE",
    "SCALE",
    "REVISION",
    "DRAWNBY",
    "CHECKEDBY",
    "SHEETNO",
    "SHEETNUMBER",
    "VENDORDWGNO",
    "DWGSIZE",
    "PROJECTTITLE",
)


def fuzzy_label_line(text: str) -> bool:
    """A scan's misspelt field label ("DRANING NO.", "REVSON NO.", "ORABNG NO."): the letters of a short line are close
    to a known label."""
    t = re.sub(r"[^A-Z]", "", text.upper().replace("0", "O"))
    if not 4 <= len(t) <= 16:
        return False
    return any(difflib.SequenceMatcher(None, t, lab).ratio() >= 0.78 for lab in _LABEL_PHRASES)
