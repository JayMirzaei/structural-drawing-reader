"""Sheet titles: what a title looks like, and repairs for titles read from a scan.

A sheet title names the drawing type ("SECOND FLOOR PLAN"), is set in capitals and sits near the
sheet number. It is found by vocabulary and position, not by being the largest text, because a logo
or the number itself is often larger.
"""

from __future__ import annotations

import difflib
import re

from drawing_reader.parse.regions import NAMES_PATTERN, SINGLE_WORD_REGION_NAMES
from drawing_reader.parse.revision_text import RE_DATE
from drawing_reader.parse.scale import RE_SCALE_BARE, normalise_scale
from drawing_reader.parse.titleblock_fields import is_label_text

RE_OCR_JUNK = re.compile(r"[?\[\]{}|<>~]")  # characters a scan puts into a line it could not read


RE_SHEET_OF = re.compile(r"\s+SHEET\s*\d+\s*(?:OF|/)\s*\d+$", re.I)  # "SHEET 1 OF 2": page furniture after a title


# Sheet title fallback. Convention: a sheet title names the drawing type ("SECOND FLOOR PLAN", "SECTIONS AND DETAILS"),
# is set in capitals, sits in the title block close to the sheet number, and may be smaller than a logo or the number
# itself -- so it is looked for by vocabulary and position, not by being the largest text.
RE_TITLE_WORD = re.compile(
    r"\b(PLANS?|ELEVATIONS?|SECTIONS?|DETAILS?|FRAMING|FOUNDATIONS?|NOTES|SCHEDULES?|LAYOUT|GENERAL|ARRANGEMENTS?|COVER ?(?:PAGE|SHEET)|"
    r"ISOMETRIC|DIAGRAMS?|ROOF|FLOORS?|STAIRS?|SITE|TYPICAL|LEGEND|INDEX|COVER|PLATFORM|MEZZANINE|LEVEL|"
    r"CONNECTIONS?|REINFORCEMENT|PILES?|FOOTINGS?|COLUMNS?|BEAMS?|BRACING|STEEL|CONCRETE|SLAB|WALLS?|KEY|TRUSS|SUPPORTS?|"
    r"SPECIFICATIONS?|ABBREVIATIONS?|SYMBOLS?|SCREW|ANCHORS?|BOLTS?|GRATING|PIPE|PIPING|BRIDGES?|GIRDERS?|ABUTMENTS?|(?:SUB|SUPER)STRUCTURES?|TANK|STRUCTURAL|MISC|"
    r"DEMOLITION|MILLWORK|ELECTRICAL|MECHANICAL|PLUMBING|CEILING|CABLE|TRAY|MODULE|LIST|REBAR|STAGING|RACK)\b",
    re.I,
)


# a numbered note / sentence, not a title
RE_NOTE_LINE = re.compile(
    r"^\s*(\(?\d{1,2}[).]|[A-Z][).]\s)|.*\b(SHALL|MUST|SHOULD|UNLESS|PROVIDE|ALLOW|ARE PER|U\.?N\.?O\.?|REQ'?D)\b|.*\d['\x22\u201d\u2033](?!-[A-Z])",
    re.I,
)


# Abbreviations of the engineering regulators whose permit-to-practice and seal text sits in title blocks
# (the Canadian provincial and territorial associations). A line naming one is a stamp, never a title.
PROFESSIONAL_BODIES = ("APEGA", "EGBC", "APEGS", "EGM", "PEO", "OIQ", "APEGNB", "PEGNL", "NAPEG", "APEY")


RE_NOT_TITLE = re.compile(
    r"\b(PERMIT|"
    + "|".join(PROFESSIONAL_BODIES)
    + r"|PRACTICE|SCALE|DRAWN|CHECKED|DESIGN(ED)?|REVISIONS?|ISSUED|PROJECT|CLIENT|CONSULTANT|"
    r"ENGINEER(S|ING)?|ARCHITECTS?|COPYRIGHT|SEAL|LTD|INC|CORP(ORATION)?|LIMITED|APPROVED|REFERENCE|DATE|SIGNATURE|"
    r"ISSUE|CONSTRUCTIONISSUE|DRAWINGNO|DRAWINGNUMBER|TECHNICAL STANDARDS|REF|DWG|DVG|DRAWING (NO|NUMBER)|UNIT NO|STREET|AVENUE|AVE|ROAD|"
    + NAMES_PATTERN  # a line naming a province or a state is an address, not a title
    + r"|CANADA|NOT FOR|FOR (CONSTRUCTION|REVIEW|TENDER))\b|\bDEPT\.?(?![A-Za-z])|\bPRINTED\b|\bPREV(?:IOUS|OUS)\b|\bNUMBER\b|ISSUEDFOR|\b(?:WITHOUT|CONSENT|LABOUR|LIABLE|OMITTED|INSTEAD|UNIT RATE)\b|OMITTEDFROM|RASTERI[SZ]ED|\bUSE ONLY\b|\bREVIS\w*\s+DESCR\w*|\bNO\.?\s*$|^\d+\s*OF\s*\d+$",
    re.I,
)


# a title-block field row ("CHECK DATE09MAR31"), never a title
RE_FIELD_ROW = re.compile(r"^(?:CHEC?KE?D?|CHKD|DRAWN|DATE|OATE|APPR(?:OVE[D]?)?|APPD|SCALE|DWN)(?:\b|(?=\d))", re.I)


def plausible_title(text: str, repeated: set[str] = frozenset(), one_word_ok: bool = False) -> bool:
    """Whether a text can be a sheet title: names a drawing type (or is a multi-word capitals phrase), and is not a
    note, label, date, scale, address, company line or a line repeated on most sheets."""
    t = text.strip()
    # a sign-off name ("J. SMITH", "A.EXAMPLE"), never a title
    if len(t.split()) <= 3 and re.search(r"\b[A-Z]\.\s?[A-Z]{4,}\b", t):
        return False
    # a sentence ("bolt as shown, see drawings for details."), never a title
    if t.endswith(".") and re.search(r"[a-z]{3}", t):
        return False
    # the revision table's column header ("DESCRIPTON")
    if len(t.split()) == 1 and any(
        difflib.SequenceMatcher(None, t.upper(), w).ratio() >= 0.8 for w in ("DESCRIPTION", "TITLE")
    ):
        return False
    if (
        sum(c.isalpha() for c in t) < 4
        or ":" in t
        or RE_DATE.search(t)
        or RE_NOT_TITLE.search(t)
        or RE_NOTE_LINE.match(t)
        or RE_SCALE_BARE.match(normalise_scale(t))
        or is_label_text(t)
        or len(t.split()) > 12
        or len(t) > 100
        or sum(c.isdigit() for c in t) > len(t) // 4
        or re.sub(r"[^a-z0-9]", "", t.lower()) in repeated
        or RE_FIELD_ROW.match(t)
        or t.endswith(",")
        or re.search(r"[^A-Za-z0-9 &/\-().,'\"#@]", t)
        or any(
            len(w) >= 3 and w.isalpha() and not re.search(r"[AEIOUY]", w.upper()) for w in re.findall(r"[A-Za-z]+", t)
        )
    ):
        return False
    if RE_TITLE_WORD.search(t) or (len(t.split()) >= 2 and is_caps(t)):
        return True
    # a single capitals word set beside the sheet number ("BEARINGS"): a real word has vowels, a garbled one does not
    return (
        one_word_ok
        and is_caps(t)
        and t.isalpha()
        and len(t) >= 6
        and sum(c in "AEIOUY" for c in t.upper()) >= 0.25 * len(t)
    )


def is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) >= 0.8 * len(letters)


_TITLE_VOCAB = frozenset(
    """FOUNDATION FOUNDATIONS PLAN PLANS DETAIL DETAILS SECTION SECTIONS ELEVATION ELEVATIONS PILE PILES LAYOUT ROOF FLOOR FRAMING MEZZANINE
    CRANE BEAM BEAMS COLUMN COLUMNS GENERAL NOTES NOTE SCHEDULE SCHEDULES PRECAST PANEL PANELS WALL WALLS SLAB SLABS STEEL CONCRETE BRACING
    DECK BASE TYPICAL TYP LEVEL UPPER LOWER MAIN GROUND SITE ANCHOR BOLT BOLTS REINFORCING CONNECTION CONNECTIONS MISC AND OF THE FOR TO WITH
    SPECIFICATION SPECIFICATIONS RTU TOP UNIT UNITS OPENING OPENINGS STRUCTURAL ADDITION ADDITIONS PLANT PLATFORM PLATFORMS AREA BRIDGE BRIDGES GIRDER GIRDERS ABUTMENT ABUTMENTS SUBSTRUCTURE SUBSTRUCTURES SUPERSTRUCTURE EXISTING NEW PARTIAL ENLARGED STAIR STAIRS ROOM BUILDING OFFICE WAREHOUSE NORTH SOUTH EAST WEST COVER""".split()
)


def fix_title_digits(text: str) -> str:
    """A scan reads a letter as a digit inside a title word ("8ECTIONS", "DETAL8"): the word is mended only when, with
    the digits turned back into letters, it lands on (or one letter from) a drafting word."""
    out = []
    for tok in text.split():
        letters = sum(c.isalpha() for c in tok)
        if (
            letters >= 3
            and any(c.isdigit() for c in tok)
            and re.fullmatch(r"[A-Za-z0-9]+", tok)
            and sum(c.isdigit() for c in tok) <= 2
        ):
            cand = tok.upper().translate(str.maketrans("0158", "OISS"))
            best = max(
                (w for w in _TITLE_VOCAB if len(w) >= 5),
                key=lambda w: difflib.SequenceMatcher(None, cand, w).ratio(),
                default="",
            )
            if best and difflib.SequenceMatcher(None, cand, best).ratio() >= 0.85 and abs(len(cand) - len(best)) <= 1:
                tok = best
        out.append(tok)
    return " ".join(out)


def split_glued_title(text: str) -> str:
    """Rotated OCR text arrives without spaces ("FOUNDATIONSPLAN"): split a run-together word when it breaks
    completely into drafting words; anything not fully explained is left as read."""
    out = []
    text = re.sub(r"(?i)\bCOVER(?=SHEET\b|PAGE\b)", "COVER ", text)  # "COVERSHEET"
    text = re.sub(r"(?<=[A-Za-z])&(?=[A-Za-z])", " & ", text)  # a scan drops the spaces round an ampersand
    text = re.sub(r"\b(\d{1,2}(?:ST|ND|RD|TH))(?=[A-Z]{4})", r"\1 ", text)  # "2NDFLOOR..." -> "2ND FLOOR..."
    for tok in text.split():
        t = tok.upper()
        if len(t) < 6 or not t.isalpha():
            out.append(tok)
            continue
        best: list[list[str] | None] = [None] * (len(t) + 1)
        best[0] = []
        for i in range(1, len(t) + 1):
            for j in range(max(0, i - 14), i):
                if (
                    best[j] is not None
                    and t[j:i] in _TITLE_VOCAB
                    and (best[i] is None or len(best[j]) + 1 < len(best[i]))
                ):
                    best[i] = best[j] + [t[j:i]]
        out.append(" ".join(best[-1]) if best[-1] and len(best[-1]) > 1 else tok)
    return " ".join(out)


_TITLE_STRAY_WORDS = (
    "ORIG",
    "GRP",
    "SERIAL",
    "NTS",
    "SHEET",
    "REV",
    "REVISION",
    "NO",
    "DWG",
    "DRAWING",
    "SCALE",
    "DATE",
    "CHECKED",
    "CHKD",
    "CHK'D",
    "DRAWN",
    "APPROVED",
    "LEGACY",
    "ISSUE",
    "PROJECT",
    "CLIENT",
    "TITLE",
    "DESIGNED",
    "NUMBER",
    "CORPORATION",
)


def _stray_label_word(tok: str) -> bool:
    """A word that is a title-block field label (maybe misread: "Drowing", "SHFET") rather than part of a title."""
    t = re.sub(r"[^A-Za-z']", "", tok).upper()
    if not t:
        return False
    if t in _TITLE_STRAY_WORDS:
        return True
    return len(t) >= 4 and any(
        abs(len(t) - len(w)) <= 1 and difflib.SequenceMatcher(None, t, w).ratio() >= 0.8 for w in _TITLE_STRAY_WORDS
    )


def trim_stray_labels(title: str) -> str:
    """Drop field-label words an OCR line-join left on the end of a title ("... PLAN Drowing No.", "... SHEET 1 REV
    NO."); a word glued from two labels ("SHFETREV") goes too. Trailing only: a title word is never removed from the
    middle."""
    toks = title.split()
    while toks and re.fullmatch(r"(?i)C?ORPORAT\w*", toks[0]):
        toks.pop(0)  # the front of a company line ("CORPORATION") cut by the scan
    for i, t in enumerate(toks):
        if len(t) >= 8 and re.search(r"GRP|ORIG", t.upper()):
            toks = toks[:i]  # a glued row of field labels (abbreviations such as ORIG, GRP) closes the title early
            if len(toks) <= 1 and not any(re.sub(r"[^A-Za-z]", "", w).upper() in _TITLE_VOCAB for w in toks):
                toks = []
            break
    while (
        len(toks) > 3
        and (_stray_label_word(toks[0]) or re.fullmatch(r"(?i)N[·./]?A", toks[0]))
        and re.sub(r"[^A-Za-z]", "", toks[0]).upper() not in _TITLE_VOCAB
    ):
        toks.pop(0)  # a label row a scan ran into the front of the title ("5CALE NTS DES1GNED N-A PUMP HOUSE ...")
    for i, t in enumerate(toks[:5]):
        w = re.sub(r"[^A-Za-z]", "", t).upper()
        if (
            len(toks) - i > 2
            and len(w) >= 5
            and i >= 1
            and (t.endswith(",") or toks[i - 1].endswith(","))
            and w not in _TITLE_VOCAB
            and max(difflib.SequenceMatcher(None, w, pv).ratio() for pv in SINGLE_WORD_REGION_NAMES) >= 0.7
        ):
            toks = toks[i + 1 :]  # "RIVERTOWN, ONTRRIO" -- the site address a scan ran into the front of the title
            break
    popped = False
    while len(toks) > 2:
        t = toks[-1]
        letters = re.sub(r"[^A-Za-z]", "", t).upper()
        if len(letters) >= 8 and difflib.SequenceMatcher(None, letters, "CLIENTREGIONPROJECT").ratio() >= 0.7:
            toks.pop()  # a row of field labels under the title (client, region, project), glued and misread by a scan
            continue
        if letters in _TITLE_VOCAB and not (popped and letters in ("UNIT", "PLANT", "PANT", "AREA")):
            break  # "NOTES", "PLAN": a drafting word closing the title is the title, whatever label it resembles
        glued = len(letters) >= 6 and any(
            letters[:i] and _stray_label_word(letters[:i]) and _stray_label_word(letters[i:])
            for i in range(3, len(letters) - 2)
        )
        if (
            _stray_label_word(t)
            or glued
            or (popped and letters in ("UNIT", "PLANT", "PANT", "AREA", "SHEET"))
            or re.fullmatch(r"(?i)(?:no|rev|sheet)\.?\|?\w{0,3}", t)
        ):
            toks.pop()
            popped = True
        else:
            break
    return " ".join(toks)
