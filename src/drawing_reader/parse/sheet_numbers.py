"""Sheet and drawing numbers: their shapes, references to them, and candidate clean-up.

Building sets number sheets "S.1" / "S-101" / "S2.10B"; industrial sets use long segmented document
numbers. Notes and callouts refer to sheets in looser spellings, so matching a reference to a real
sheet number is tolerant of dots, dashes and series prefixes.
"""

from __future__ import annotations

import difflib
import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.layout import same_row
from drawing_reader.parse.revision_text import RE_DATE

RE_SHEET_NO = re.compile(
    r"^(?:[A-Z]{1,2}[-.]?\s?\d{1,3}[A-Z]?"  # S.1, S1, A-101, C01
    r"|[A-Z]{1,2}\d{1,3}\.\d{1,2}[A-Z]?"  # S1.01, S2.04B, S301.2D, SR1.03
    r"|[A-Z]{1,2}\d{1,3}-\d{1,3}[A-Z]?"  # S01-02, S3-1, A01-01, M40-01 (discipline-section-sheet,
    #                                                  1-3 digits either side of the dash)
    r"|[A-Z]{1,2}-\d{3,4}-\d{2}"  # S-1420-08 (series-drawing-sheet, a bridge standard's four-digit drawing)
    r"|[A-Z]{1,2}-\d{1,3}-\d{1,3}[A-Z]?"  # S-2-37, S-6-4 (discipline-area-sheet, dashes throughout)
    r"|[A-Z]\.\d{1,2}(?:\.\d{1,2}){1,4})$"  # S.2.4, A.4.2.7, C.0.5.2, C.3.1.4.12 (a multi-segment dot
    #                                                  convention: one letter then 2-5 dot-separated numeric
    #                                                  segments -- distinct from the single-segment "S.1" case
    #                                                  above and from "S1.02"'s no-dot-before-first-digit shape)
)


# Convention: industrial/EPC sets number sheets with a long segmented document number, not S-101
# ("PX-12-GEN-00-310-04", "AB123-S-180", "B20.01-7C-00031", "02-S-DET-0005"): letters and digits in 2-7 segments
# joined by - or . (OCR may give an em dash). Only used when no S.x/A-101 style number is in the title block.
RE_DOC_NO = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]{1,8}(?:[.\-][A-Za-z0-9]{1,8}){1,6}$")


# "30417-C": numeric drawing number, scans only (see parse_titleblock)
RE_DRAWING_NO = re.compile(r"^\d{4,6}-[A-Za-z]?$")


RE_SHEET_REF = re.compile(
    r"\b(?:DRWS?\.?|DRAWINGS?|DWGS?\.?|SHEETS?|SEE)\b[^A-Z0-9]*((?:S\s?[-.]?\s?\d{1,3}[A-Z]?(?:\s*,?\s*(?:AND\s+)?)?)+)",
    re.I,
)


# A sheet id in note text: "S-503", "S.5", "S5". Both separators are common, so both are accepted, and
# the separator is captured so a reference can be reported as printed.
RE_SHEET_TOKEN = re.compile(r"S\s?([-.]?)\s?(\d{1,3}[A-Z]?)", re.I)


# Detail/section number over sheet id, written inline as "N/SHEET" (e.g. "SEE DETAIL 4/S502",
# "SEE SECT. B2/S601", "SEE ELEV.2/S302") -- distinct from RE_SHEET_REF's "SEE/DWG/SHEET S###"
# convention, and from the drafted split-circle callout bubble (parse_grids_callouts_elevations).
RE_DETAIL_REF = re.compile(r"\b([A-Z]?\d{1,2}[A-Z]?)\s*/\s*(S\s?[.\-]?\s?\d{1,3}[A-Z]?(?:-\d{1,3}[A-Z]?)?)\b", re.I)


def join_split_numbers(runs: list[TextRun]) -> list[TextRun]:
    """A segmented document number OCR'd as two runs that meet at a dash or dot ("AB123-" + "-S-4010-1"): the joined
    text, as one run spanning both, for each adjacent same-row pair whose join reads as a document number."""
    out = []
    for m in runs:  # a lone dash between two runs of one row ("K-A101-2200" "-" "301"): the three, joined
        if m.text.strip() not in ("-", "\u2013", "\u2014"):
            continue
        for a in runs:
            if (
                a is m
                or not same_row(a, m)
                or not (-0.6 * m.size <= m.bbox[0] - a.bbox[2] <= 0.8 * m.size)
                or a.text.rstrip().endswith("-")
            ):
                continue
            for b in runs:
                if (
                    b is m
                    or b is a
                    or not same_row(b, m)
                    or not (-0.6 * m.size <= b.bbox[0] - m.bbox[2] <= 0.8 * m.size)
                ):
                    continue
                text = (a.text.strip() + "-" + b.text.strip()).replace(" ", "")
                if 8 <= len(text) <= 32 and RE_DOC_NO.match(text) and re.fullmatch(r"\d{1,4}[A-Z]?", b.text.strip()):
                    out.append(
                        TextRun(
                            id=f"{a.id}+{m.id}+{b.id}",
                            text=text,
                            bbox=(
                                min(a.bbox[0], b.bbox[0]),
                                min(a.bbox[1], b.bbox[1]),
                                max(a.bbox[2], b.bbox[2]),
                                max(a.bbox[3], b.bbox[3]),
                            ),
                            dir=a.dir,
                            size=max(a.size, b.size),
                            block=a.block,
                            conf=min(a.conf, m.conf, b.conf),
                        )
                    )
    for a in runs:
        # a scan can drop the dash that follows the project prefix: "PX1" + "12-STR-A00-0031-002"
        bare_prefix = bool(re.fullmatch(r"[A-Z]{1,3}\d", a.text.strip()))
        if not a.text.rstrip().endswith(("-", ".")) and not bare_prefix:
            continue
        for b in runs:
            if (
                b is a
                or not same_row(a, b)
                or not (-0.6 * a.size <= b.bbox[0] - a.bbox[2] <= (1.2 if bare_prefix else 0.8) * a.size)
            ):
                continue
            if bare_prefix:
                if re.match(r"\d{2}-[A-Z]{2,4}-", b.text.strip()):
                    text = f"{a.text.strip()}-{b.text.strip()}"
                    if 8 <= len(text) <= 32 and RE_DOC_NO.match(text):
                        out.append(
                            TextRun(
                                id=f"{a.id}+{b.id}",
                                text=text,
                                bbox=(
                                    min(a.bbox[0], b.bbox[0]),
                                    min(a.bbox[1], b.bbox[1]),
                                    max(a.bbox[2], b.bbox[2]),
                                    max(a.bbox[3], b.bbox[3]),
                                ),
                                dir=a.dir,
                                size=max(a.size, b.size),
                                block=a.block,
                                conf=min(a.conf, b.conf),
                            )
                        )
                continue
            text = (
                a.text.strip() + b.text.strip().lstrip("-.").strip()
                if b.text.lstrip().startswith(("-", "."))
                else a.text.strip() + b.text.strip()
            )
            text = text.replace(" ", "")
            if 8 <= len(text) <= 32 and RE_DOC_NO.match(text):
                out.append(
                    TextRun(
                        id=f"{a.id}+{b.id}",
                        text=text,
                        bbox=(
                            min(a.bbox[0], b.bbox[0]),
                            min(a.bbox[1], b.bbox[1]),
                            max(a.bbox[2], b.bbox[2]),
                            max(a.bbox[3], b.bbox[3]),
                        ),
                        dir=a.dir,
                        size=max(a.size, b.size),
                        block=a.block,
                        conf=min(a.conf, b.conf),
                    )
                )
    return out


_RE_DOC_LABEL = re.compile(r"^[A-Z.]{0,6}?(?:DWG|DRAWING|DRG|SHEET)\.?(?:NO|NUMBER|#)\.?:?", re.I)


# a labelled field that is not the drawing number
_RE_NOT_DOC = re.compile(r"^(?:DATE|DOTE|DATED|JOB|PERMIT|PROJECT|PROJ|REV|SCALE|FILE)", re.I)


def document_number_text(r) -> str:
    """The run's text as a candidate document number: spaces and dash variants normalised, a glued
    "DWG.NO." label dropped; "" when it is some other labelled field ("DATE31.04.09", "PERMIT NO:P0000")."""
    t = r.text.replace(" ", "").replace("\u2014", "-").replace("\u2013", "-")
    if r.conf < 1.0:
        t = re.sub(r"(?<=[A-Z0-9])[=~](?=[A-Z0-9])", "-", t)  # a scan reads a dash as "=" or "~"
    t = _RE_DOC_LABEL.sub("", t)
    if re.fullmatch(r"(?i)(?:FAX|TEL|PH|PHONE|CELL)[:.]?\+?[\d()\-.]{7,}", t):
        return ""  # a telephone / fax line ("FAX555-010-0199"), never a number
    if re.fullmatch(r"(?i)\d{1,2}-\d{1,2}-\d{1,3}-\d{1,2}-?W\d[M]?|\d{6,8}W\dM", t):
        return ""  # a land location ("12-34-56-7-W4M"), never a number
    if re.fullmatch(
        r"(?i)(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[-.]?\d{1,2}[-.]?\d{2,4}|\d{1,2}[-.]?(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[-.]?\d{2,4}",
        t,
    ):
        return ""  # a plot date ("NOV-04-2022"), never a number
    if re.search(r"(?i)APPROVED", t):
        return ""  # a stamp glued to a mark ("DE5.APPROVED"), never a number
    return "" if ":" in t or _RE_NOT_DOC.match(t) else t


_NUMBER_LABELS = ("DRAWINGNO", "DRAWINGNUMBER", "DRAWING#", "DWGNO", "DWG#", "SHEETNO", "SHEETNUMBER", "SHEET#")


class _LabelMatch:
    """Stands in for the `re.Match` of a number label: `start()` is where the label starts in the text."""

    def __init__(self, start: int):
        self._s = start

    def start(self) -> int:
        return self._s


def fuzzy_number_label(norm: str):
    """A scan's misspelt number label ("DRABINGNO", "DRAMNGNO") -- the end of `norm` is within a couple of letters of a
    known one.
    Only the longer spellings (a lone "SHEET" or "NO" must never count), so a stray word is not taken for a label."""
    for lab in _NUMBER_LABELS:
        if len(lab) < 8 or len(norm) < len(lab) - 1:
            continue
        tail = norm[-len(lab) :]
        if difflib.SequenceMatcher(None, tail, lab).ratio() >= 0.8:
            return _LabelMatch(len(norm) - len(lab))
    return None


def is_page_count(txt: str) -> bool:
    """ "OF6" (a scan reads "1 OF 6" as pieces), "1OF6", "SHT.2OF4": the "n of m" beside a sheet-number label, never a
    number."""
    return bool(re.fullmatch(r"(?:SH(?:EE)?T?\.?)?\d*(?:OF|/)\d+", txt.upper().replace(" ", "")))


def labelled_number_ok(txt: str) -> bool:
    """A value under or beside a "DRAWING NO." label is the number even when it breaks the usual shapes: letters then
    a leading-zero number ("S0701"), digits only ("3006"), a scan's number that lost its prefix
    ("-12-STR-A41-0001-002"). Not a date, not a word."""
    if txt.strip().endswith(("-", ".")):
        return False  # a run cut short ("PX1-"): the rest of the number is in the next run
    t = txt.strip().strip("-").upper()
    if is_page_count(t):
        return False
    if not (3 <= len(t) <= 32) or not re.fullmatch(r"[A-Z0-9][A-Z0-9\-._/]*", t) or not re.search(r"\d", t):
        return False
    if RE_DATE.search(txt) or re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", t):
        return False
    return True


def sheet_ref_matches(ref: str, real: str) -> bool:
    """A note's inline reference ('SEE S30', 'DWG S30') often names just the series prefix of a
    multi-sheet group ('S30-01', 'S30-02', ...) rather than one exact sheet number; accept an exact
    match or a match up to the next '-' segment, ignoring periods/spaces either side. Notes also
    sometimes drop the dash a real sheet number uses ('S301' vs. title-block 'S-301'); accept that
    too, as a separate check, without loosening the series-shorthand check above."""
    r = re.sub(r"[.\s]", "", ref.upper())
    h = re.sub(r"[.\s]", "", real.upper())
    if r == h or h.startswith(r + "-"):
        return True
    return r.replace("-", "") == h.replace("-", "")
