"""The router: run every rule, keep the most confident answer, fall back to an LLM provider.

Rules answer lookup questions deterministically and for free. A question no rule answers with
confidence >= THRESHOLD goes to the provider (when one is configured) with the rule hits as hints.
"""

from __future__ import annotations

from drawing_reader.qa.answer import MIN_CONFIDENCE, OCR_ANSWER_CAP, THRESHOLD, Answer
from drawing_reader.qa.rules.combined import rule_multi_property
from drawing_reader.qa.rules.geometry import rule_angles, rule_dimensions, rule_elevations, rule_grids
from drawing_reader.qa.rules.loads import rule_loads, rule_no_loads
from drawing_reader.qa.rules.materials import rule_component_spec, rule_concrete, rule_grout, rule_materials
from drawing_reader.qa.rules.members import rule_member_lookup, rule_sections, rule_weld
from drawing_reader.qa.rules.notes import rule_general_notes, rule_note_lookup, rule_text_search
from drawing_reader.qa.rules.sheets import rule_callouts, rule_missing, rule_sheets, rule_views
from drawing_reader.qa.rules.titleblock import rule_location, rule_project, rule_revisions, rule_scale
from drawing_reader.qa.text import is_compound, tokens
from drawing_reader.schema import Index

# rule_multi_property must precede rule_materials/rule_component_spec/rule_dimensions here: its
# merged confidence is the max of its parts' own confidences (by design), which ties the part-rule
# it drew that max from -- answer_by_rules()'s stable sort keeps ties in this list's order, so the
# fuller merged answer only wins the tie by appearing first.
RULES = [
    rule_sheets,
    rule_missing,
    rule_revisions,
    rule_scale,
    rule_location,
    rule_project,
    rule_sections,
    rule_member_lookup,
    rule_multi_property,
    rule_materials,
    rule_angles,
    rule_elevations,
    rule_grids,
    rule_callouts,
    rule_grout,
    rule_loads,
    rule_no_loads,
    rule_component_spec,
    rule_views,
    rule_weld,
    rule_dimensions,
    rule_note_lookup,
    rule_general_notes,
    rule_concrete,
    rule_text_search,
]


def answer_by_rules(question: str, idx: Index) -> list[Answer]:
    q = question.lower().strip()
    toks = tokens(q)
    out = []
    for rule in RULES:
        try:
            a = rule(q, toks, idx)
        except Exception as e:  # noqa: BLE001  a rule must never take the app down
            a = Answer(f"(rule {rule.__name__} failed: {e})", [], 0.0, f"rule:{rule.__name__}:error")
        if a:
            a = a.with_sheets(idx)
            if idx.from_ocr:
                # Convention: evidence read from a scan is approximate, so the answer says so and
                # never claims more than OCR_ANSWER_CAP, whatever the rule's own confidence.
                a.confidence = min(a.confidence, OCR_ANSWER_CAP)
                a.caveats.append("Read from a scanned page by OCR -- check numbers and spelling against the sheet.")
            out.append(a)
    out.sort(key=lambda a: -a.confidence)
    return out


def answer(question: str, idx: Index, llm=None, sheets_for_llm=None) -> Answer:
    """Rules first; LLM (if provided and enabled) when rules are not confident.

    `sheets_for_llm` names the sheets the model is shown; by default it picks the most relevant."""
    cands = answer_by_rules(question, idx)
    best = cands[0] if cands else None
    if best and is_compound(question):
        best.confidence = min(best.confidence, THRESHOLD - 0.05)
        best.caveats.append(
            "This looks like a multi-part or comparison question; a single rule only covers part of it."
        )
    if best and best.confidence >= THRESHOLD:
        return best
    llm_error: Answer | None = None
    if llm is not None and getattr(llm, "enabled", False):
        hint_ids = [fid for a in cands[:3] for fid in a.fact_ids][:40]
        res = llm.ask(question, idx, hint_ids=hint_ids, sheets=sheets_for_llm or [])
        if res is not None and res.method == "llm:error":
            llm_error = res  # keep the rule answer; the failure becomes a caveat
        elif res is not None:
            return res.with_sheets(idx)
    if best and best.confidence >= MIN_CONFIDENCE:
        if llm_error is not None:
            best.caveats.append(
                "Low-confidence rule answer; the LLM call failed so it could not interpret further. "
                + "; ".join(llm_error.caveats)
            )
        else:
            best.caveats.append("Low-confidence rule answer; no LLM was available to interpret further.")
        return best
    if llm_error is not None:
        return llm_error.with_sheets(idx)
    return Answer(
        "I could not find this in the drawing set. Try naming the sheet, the member, or a word that appears on the drawing.",
        [],
        0.0,
        "none",
    )
