"""A rule that composes other rules' answers for one component with several properties."""

from __future__ import annotations

from drawing_reader.qa.answer import THRESHOLD, Answer
from drawing_reader.qa.rules.geometry import rule_dimensions
from drawing_reader.qa.rules.materials import rule_component_spec, rule_materials
from drawing_reader.qa.vocabulary import PROPERTY_CLASSES
from drawing_reader.schema import Index


def rule_multi_property(q, toks, idx: Index):
    """A question naming one component and >=2 of its properties (size / thickness / length /
    diameter / grade) is one lookup with several targets -- not is_compound's comparison/multi-ask
    case, which flags a genuinely different question shape -- and each property lives in a
    different rule's territory (dimension strings, '<n><unit> <property>' note spans, material
    clauses), so no single rule can answer it in full on its own. This composes their existing,
    already-confident answers; it never re-implements their matching logic."""
    classes = {c for c, ws in PROPERTY_CLASSES.items() if ws & set(toks)}
    if len(classes) < 2:
        return None

    parts: list[tuple[Answer, set[str]]] = []

    if "size" in classes:
        a = rule_dimensions(q, toks, idx)
        if a is not None and a.confidence >= THRESHOLD:
            parts.append((a, {"size"}))

    comp_classes = classes & {"thick", "long", "dia"}
    if comp_classes:
        a = rule_component_spec(q, toks, idx)
        if a is not None and a.confidence >= THRESHOLD:
            parts.append((a, set(comp_classes)))

    if "grade" in classes or "size" in classes:
        a = rule_materials(q, toks, idx)
        if a is not None and a.confidence >= THRESHOLD:
            mat_classes = set()
            if "grade" in classes:
                mat_classes.add("grade")
            if "size" in classes and any((f := idx.get(fid)) and f.attrs.get("size") for fid in a.fact_ids):
                mat_classes.add("size")
            if mat_classes:
                parts.append((a, mat_classes))

    if len(parts) < 2:
        return None
    covered_sets = [cov for _, cov in parts]
    union = set().union(*covered_sets)
    if not all(union > cov for cov in covered_sets):
        return None  # a single part already covers everything the merge would -- nothing gained

    fact_ids: list[str] = []
    caveats: list[str] = []
    for a, _ in parts:
        for fid in a.fact_ids:
            if fid not in fact_ids:
                fact_ids.append(fid)
        for c in a.caveats:
            if c not in caveats:
                caveats.append(c)
    confidences = [a.confidence for a, _ in parts]
    if len(set(confidences)) > 1:
        methods = ", ".join(a.method for a, _ in parts)
        caveats.append(f"Combined from {methods}; the lowest-confidence part scored {min(confidences):.2f}.")

    text = "\n\n".join(a.text for a, _ in parts)
    return Answer(text, fact_ids, max(confidences), "rule:multi-property", caveats=caveats)
