"""Material clauses: standard citations (ASTM, CSA), yield strengths and component sizes."""

from __future__ import annotations

import re

RE_ASTM = re.compile(
    r"\b(ASTM\s+[A-Z]\d{2,4}(?:\s?/\s?[A-Z]\d{2,4}M?)?(?:\s?[A-Z]\d?)?"
    r"|CSA\s*-?\s*[A-Z]?\d{2,4}(?:\.\d+)?(?:M?-?\d{3}[A-Z]{0,2}|-M)?"  # grade kept: "CSA G40.21M300W", "G40.21M-350A"
    r"|CSSBI\s?\d{1,3}M?)\b",
    re.I,
)


# Standards a material clause cites that are not a material grade: design codes (CSA S16, S6, S136, A23.3, O86),
# welding standards (CSA W47.1, W48, W59, W55.3, AWS D1.1) and coating standards (CSA G164, ASTM A123, A153,
# A780). "HOT DIP GALVANIZE ALL STEEL TO CSA G164" names how steel is coated, not what steel it is.
RE_NON_GRADE_STANDARD = re.compile(
    r"^(?:CSA\s*-?\s*(?:S16|S6|S136|S157|S304|S413|A23\.[123]|O86|W47|W48|W59|W55|G164|G189)"
    r"|ASTM\s+(?:A123|A153|A780|A384|A385|B695)|AWS\s+D1)(?![0-9])",
    re.I,
)


def spec_role(spec: str) -> str:
    """ "grade" for a material specification (CSA G40.21 350W, ASTM A325), "standard" for a design, welding or
    coating standard (see RE_NON_GRADE_STANDARD); "" when the clause cites nothing."""
    if not spec:
        return ""
    return "standard" if RE_NON_GRADE_STANDARD.match(spec.strip()) else "grade"


RE_FY = re.compile(r"F\s?y\s?=\s?(\d{2,4})\s?MPa", re.I)


# Prose form of a yield strength ("MINIMUM YIELD STRESS OF 50,000psi (345MPa)"): the drawing's own MPa value
# in parentheses wins; otherwise MPa as written, otherwise a psi/ksi value converted by code (never invented).
RE_YIELD = re.compile(
    r"\bYIELD\s+(?:STRESS|STRENGTH|POINT)\b[^.\d]{0,50}?(\d[\d,]*(?:\.\d+)?)\s*(PSI|KSI|MPA)\b"
    r"(?:\s*\(\s*(\d+(?:\.\d+)?)\s*MPA\s*\))?",
    re.I,
)


RE_FY_MAX = re.compile(r"F\s?y\s?max\s?=\s?(\d{2,4})\s?MPa", re.I)


RE_SIZE = re.compile(r'\d+(?:-\d+/\d+)?(?:\.\d+)?\s?(?:"|”|mm)|\bM\d{1,2}\b', re.I)


def prose_yield_mpa(body: str) -> list[str]:
    """MPa values from prose yield-strength statements (see RE_YIELD)."""
    out = []
    for m in RE_YIELD.finditer(body):
        raw = m.group(1).replace(",", "")
        unit = (m.group(2) or "").upper()
        if m.group(3):
            out.append(m.group(3))
        elif unit == "MPA":
            out.append(raw)
        elif unit == "PSI":
            out.append(str(round(float(raw) * 0.00689476)))
        elif unit == "KSI":
            out.append(str(round(float(raw) * 6.89476)))
    return out
