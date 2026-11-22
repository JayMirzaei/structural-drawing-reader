"""Post-processing of recognised text runs: merging passes, paragraph blocks, vertical text, number repair."""

from __future__ import annotations

import re


def merge_runs(first: list, extra: list) -> list:
    """The first pass and a supplementary pass as one list: an `extra` run overlapping a first-pass run (IoU > 0.4) is
    the same text, and replaces it only when it was read with clearly more confidence (0.1 more) and a different text;
    otherwise it is added."""
    out = list(first)
    for t in extra:
        best = None
        for f in out:
            v = iou(f.bbox, t.bbox)
            if v > 0.4 and (best is None or v > best[0]):
                best = (v, f)
        if best is None:
            out.append(t)
        elif t.text != best[1].text and t.conf > best[1].conf + 0.1:
            f = best[1]
            f.text, f.bbox, f.size, f.conf, f.dir = t.text, t.bbox, t.size, t.conf, t.dir
    return out


def regroup(runs: list) -> None:
    """Vertical text direction and paragraph blocks for a page's runs after runs from another pass were merged in."""
    fix_vertical(runs)
    group_blocks(runs)


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def fix_vertical(runs: list) -> None:
    """A tall, narrow text box is text running up the page (a vertical dimension, a column label): the detector's box
    is axis-aligned and the recogniser reads it correctly, but `ocr_page` recorded it as a horizontal run whose size
    was the box's long side. Set its direction to upward (0, -1) and its size to the short side. Idempotent: running
    it again after runs from another pass are merged in changes nothing already fixed."""
    for r in runs:
        w, h = r.bbox[2] - r.bbox[0], r.bbox[3] - r.bbox[1]
        if tuple(r.dir) == (1.0, 0.0) and w > 0 and h >= 1.5 * w and len(r.text.strip()) >= 2:
            r.dir = (0.0, -1.0)
            r.size = round(w, 1)


def group_blocks(runs: list) -> None:
    """Give wrapped lines of one paragraph the same `block` id, as a vector PDF's own paragraph blocks do
    (parse_notes joins a note's wrapped lines by block). Convention: a note's lines are left-aligned and
    their top-to-top pitch is under 0.8 x the text height; a new numbered/lettered item starts after a
    visibly larger gap. OCR boxes of one font vary a few points in height, so the larger of the two
    heights is used and the sizes must be within 30% of each other."""
    followed: set[int] = set()
    block = 0
    for r in sorted(runs, key=lambda r: r.bbox[1]):
        best = None
        for p in runs:
            if p is r or id(p) in followed or p.bbox[1] >= r.bbox[1]:
                continue
            ref = max(r.size, p.size)
            pitch = r.bbox[1] - p.bbox[1]
            if (
                pitch <= 0.8 * ref
                and abs(r.bbox[0] - p.bbox[0]) <= 0.8 * ref
                and min(r.size, p.size) >= 0.7 * ref
                and r.bbox[1] - p.bbox[3] < 0.5 * ref
                and (best is None or pitch < best[0])
            ):
                best = (pitch, p)
        if best:
            r.block = best[1].block
            followed.add(id(best[1]))
        else:
            block += 1
            r.block = block


_RE_FULL = re.compile(r"^\d{4,6}-([A-Za-z])$")


_RE_CUT = re.compile(r"^(\d{4,6})-$")


_RE_NODASH = re.compile(r"^(\d{4,6})[=_ ]?([A-Za-z])$")  # "30417C", "30418=C"


def repair_drawing_numbers(sheets) -> None:
    """OCR garbles "30418-C": the letter is dropped ("30418-") or the dash is read as "=" or lost.
    Drawing numbers in one set share a suffix, so these get the dominant suffix/dash back -- only
    when one suffix clearly dominates (>= 3 full numbers, >= 60% the same letter), and only in the
    bottom fifth of the page where the title block is; otherwise text is left as read."""
    from collections import Counter

    suffixes = Counter(m.group(1).upper() for s in sheets for r in s.runs if (m := _RE_FULL.match(r.text)))
    if sum(suffixes.values()) < 3:
        return
    letter, n = suffixes.most_common(1)[0]
    if n < 0.6 * sum(suffixes.values()):
        return
    for s in sheets:
        for r in s.runs:
            if r.bbox[1] <= 0.8 * s.height:
                continue
            if _RE_CUT.match(r.text):
                r.text += letter
            elif (m := _RE_NODASH.match(r.text)) and m.group(2).upper() == letter:
                r.text = f"{m.group(1)}-{letter}"
