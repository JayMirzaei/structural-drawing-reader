"""Dates and revision-table vocabulary: date shapes, column headers, revision codes."""

from __future__ import annotations

import re

# "0.A.A", "O.B.0": a revision code, never a word of a title
RE_REV_CODE = re.compile(r"^[0-9O](?:\.[A-Z0-9]\.[A-Z0-9]|\.[A-Z0-9]{2}|[A-Z0-9]\.[A-Z0-9])$")


RE_DATE = re.compile(
    r"(\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+\d{1,2}(,?\s+\d{2,4})?\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}[-.]\d{2}[-.]\d{2}\b|\b(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.\d{2,4}\b)",
    re.I,
)


# Date-shaped revision-table cells ("JUL 14", "2031", "OCT", "04/2031", "MAR. 09/2031", "2031-05-14", "22.08.31").
_MONTH = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*\.?"


RE_DATEISH = re.compile(
    rf"^(?:{_MONTH}(?:\s*\d{{1,2}}(?:[,/]\s?\d{{2,4}})?)?|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{1,2}}[/.]\d{{4}}"
    rf"|\d{{4}}(?:[-./]\d{{1,2}}[-./]\d{{1,2}})?|\d{{1,2}}\s*{_MONTH}\s*\d{{2,4}})$",
    re.I,
)


RE_LEADING_DATE = re.compile(
    rf"^((?:{_MONTH}\s*\d{{1,2}}(?:[,/]\s?\d{{2,4}})?|\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}))\s+(\S.*)$",
    re.I,
)


REV_NUM_HEADERS = {"REV", "REV.", "I/R", "NO", "NO.", "#"}


REV_DESC_HEADERS = {"ISSUED FOR", "DESCRIPTION", "REVISIONS", "REVISION"}


# A revision-history table's own column-header words (e.g. "DATE | DESCRIPTION | ISSUE"): a bare "DATE" header in this
# row sits beside "DESCRIPTION" the same way a real title-block
# "DATE:" label sits beside its value, so the key/value scan below needs to reject these the same
# way it already rejects a neighboring TITLEBLOCK_KEYS label as a false "value".
REV_TABLE_HEADER_WORDS = {"DESCRIPTION", "ISSUED FOR", "ISSUE"}


RE_REV_NUM_HDR = re.compile(r"^(?:REV\.?|REV\.?\s*(?:NO\.?|#)|REVISION(?:\s*NO\.?)?|ISSUE|NO\.?|#|MARK)$", re.I)


RE_REV_DESC_HDR = re.compile(
    r"^(?:DESCRIPTION|ISSUED FOR|REVISION\s*DESCRIPTION|DESCRIPTION OF REVISIONS?|REMARKS|COMMENTS)$", re.I
)


RE_REV_DATE_HDR = re.compile(
    r"^(?:DATE|DATED|YY(?:YY)?[-/.]MM[-/.]D[DO]|DD[-/.]MM[-/.]YY(?:YY)?|MM[-/.]DD[-/.]YY(?:YY)?)$", re.I
)


def reads_like_a_note(desc: str) -> bool:
    """A numbered sentence of the general notes ("4. ALL DIMENSIONS SHALL BE VERIFIED ...") is no revision row: it says
    "shall" / "must", or
    runs long without naming an issue."""
    return bool(
        re.search(r"\bSHALL\b|\bTO BE\b|\bMUST\b|\bREFER TO\b|\bGENERAL NOTES\b", desc, re.I)
        or (
            len(desc) > 70
            and not re.search(r"ISSUE|REVIS|PERMIT|TENDER|AS-?BUILT|RECORD|\bBID\b|\bIFC\b|\bIFR\b|REVIEW", desc, re.I)
        )
    )
