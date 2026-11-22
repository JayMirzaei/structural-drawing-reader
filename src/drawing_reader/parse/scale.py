"""Scale statements: the regexes that recognise them and the helpers that normalise them.

A drawing states its scale as a metric ratio ("1:50"), an imperial equation ('3/4" = 1'-0"'), or a
phrase ("N.T.S.", "AS NOTED"). Scans and CAD exports spell the inch and foot marks many ways, so
text is normalised before matching.
"""

from __future__ import annotations

import difflib
import re

# The metric ratio ("1:100") is one convention; architectural and detail sheets commonly state the
# scale as an imperial fraction of an inch instead ("3/4\" = 1'-0\""). View-title detection gates on
# RE_SCALE matching, so without this alternative every view drawn under the imperial convention would
# be invisible, not just its scale.
RE_SCALE = re.compile(
    r"^(?:SCALE\s*:?\s*)?(1\s?:\s?\d{1,4}(?:\.\d+)?|AS INDICATED|N\.?T\.?S\.?|NTS|"
    r"\d{1,2}(?:/\d{1,2})?\"\s*=\s*\d{1,2}'-\d{1,2}\"?)$",
    re.I,
)


# Sheet-level scale, read from a single run. Convention: a drawing states its scale as "SCALE: 1:50", "1/8\"=1'-0\"",
# "N.T.S." or "AS SHOWN", either with a SCALE label in the same run, or (bare form) inside the title block. Scans and
# CAD exports spell the inch/foot marks many ways (prime, curly quotes, degree sign, asterisk), so `normalise_scale`
# maps them first.
_SCALE_VAL = (
    r"(1\s?:\s?\d{1,4}(?:\.\d+)?|\d{1,2}(?:/\d{1,2})?\s*[\"']?\s*=\s*\d{1,3}\s*'(?:\s*-?\s*\d{1,2}(?:/\d{1,2})?\s*\"?)?"
    r"|N\.?\s?T\.?\s?S\.?|AS\s+(?:SHOWN|NOTED|INDICATED)|NOT\s+TO\s+SCALE)"
)


# "Scole", "Soole": OCR misreads of the word
_SCALE_LABEL = r"(?:(?:DWG|DRAWING|SHEET)\.?\s*)?S[co][aod]l[ec]{0,2}s?\s*[:;,.=-]?\s*"


_SCALE_TAIL = r"(?:\s*\(?(?:U\.?N\.?O\.?|TYP\.?)\)?)?[\s.,;]*$"


RE_SCALE_LABELLED = re.compile("^" + _SCALE_LABEL + _SCALE_VAL + _SCALE_TAIL, re.I)


RE_SCALE_BARE = re.compile("^" + _SCALE_VAL + _SCALE_TAIL, re.I)


RE_SCALE_LABEL_ONLY = re.compile("^" + _SCALE_LABEL.rstrip() + "$", re.I)


_SCALE_WORDS = {"ASINDICATED": "AS INDICATED", "ASSHOWN": "AS SHOWN", "ASNOTED": "AS NOTED"}


def normalise_scale(t: str) -> str:
    """Run text with OCR/CAD spellings of the foot and inch marks mapped to ' and \", and a ratio's ';' read as ':'."""
    t = t.strip().translate(
        {0x2032: "'", 0x2019: "'", 0x2018: "'", 0x2033: '"', 0x201D: '"', 0x201C: '"', 0xB0: '"', ord("*"): '"'}
    )
    t = re.sub(r"(\d)\s*;\s*(\d)", r"\1:\2", t)
    sq = re.sub(r"[^A-Z]", "", t.upper())
    if sq in _SCALE_WORDS and not re.search(r"\d|\s", t):
        return _SCALE_WORDS[sq]  # a scan drops the space: "ASSHOWN"; a spelling with its space ("As indicated") is kept
    # a scan's "AS INOICATEO" / "AS SHOWM"
    if not re.search(r"\d", t) and 7 <= len(sq) <= 13 and sq not in _SCALE_WORDS:
        for lab, canon in _SCALE_WORDS.items():
            if abs(len(sq) - len(lab)) <= 1 and difflib.SequenceMatcher(None, sq, lab).ratio() >= 0.8:
                return canon.strip()
    return t


def canonical_scale(v: str, exact: bool = False) -> str:
    """Canonical spelling of a scale ("1:50", "NTS"); `exact` keeps a vector text layer's own spelling."""
    v = re.sub(r"\s+", " ", v.strip())
    if exact:
        return v
    if re.match(r"^1\s?:", v):
        return re.sub(r"\s", "", v)
    v = re.sub(r"^(\d{1,2}(?:/\d{1,2})?)\s*[\"']?\s*=\s*", r'\1"=', v)  # the left side of an imperial scale is inches
    if re.match(r"^N\.?\s?T\.?\s?S\.?$", v, re.I):
        return "NTS"
    return v.upper() if v[0].isalpha() else v.replace(" ", "")
