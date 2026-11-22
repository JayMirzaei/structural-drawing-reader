"""Set-level repairs for scanned (OCR) sets.

A set numbers its sheets in one scheme and reuses a few dozen member sizes, so a value read badly on
one sheet can be completed or flagged from its siblings. Nothing here runs on vector PDFs.
"""

from __future__ import annotations

import re
from collections import Counter

from drawing_reader.ingest import Document
from drawing_reader.parse.layout import is_horizontal
from drawing_reader.schema import Index

_DIGIT_FOR_LETTER = {"3": "B", "8": "B", "5": "S", "0": "D", "6": "G", "2": "Z", "1": "I"}


def repair_sheet_numbers(idx: Index, doc: Document | None = None) -> None:
    """Convention: a set numbers its sheets in one scheme, so a number read from a scan can be completed from its
    siblings. (1) Document numbers ("PX1-12-STR-A41-0001-002") share leading parts; a number that starts partway
    ("-12-STR-A41-0001-002", "12-STR-A42-0001-006", "STR-A41-0001-006") gets the leading parts that 90% of the
    well-formed numbers share. (2) A short number whose first character is a digit where its siblings have a letter
    ("3006" among "B001", "S002"): the digit is the letter it is most often misread as, and only if a sibling of the
    same shape starts with that letter. Nothing else is changed."""
    nums = [s.number for s in idx.sheets]
    renames: dict[int, str] = {}
    # (4) A sheet whose number is the project / document id every other sheet repeats ("A0042B-0025" on two sheets) or
    # a page fallback, among siblings numbered by bare digits ("201"): its own number is the digits in the block's
    # foot, nearest the corner, when its label was unread.
    if doc is not None:
        digit_sibs = [n for n in nums if re.fullmatch(r"\d{3,4}", n)]
        if digit_sibs and len({len(n) for n in digit_sibs}) == 1:
            width = len(digit_sibs[0])
            for i, sh in enumerate(doc.sheets):
                if (
                    re.fullmatch(r"\d{3,4}", nums[i])
                    or not (re.fullmatch(r"P\d+", nums[i]) or nums.count(nums[i]) > 1)
                    or not any(r.conf < 1.0 for r in sh.runs)
                ):
                    continue
                cand = [
                    r
                    for r in sh.runs
                    if is_horizontal(r)
                    and r.conf >= 0.9
                    and re.fullmatch(rf"\d{{{width}}}", r.text.strip())
                    and r.bbox[0] > 0.55 * sh.width
                    and r.bbox[1] > 0.6 * sh.height
                    and r.text.strip() not in nums
                ]
                if cand:
                    renames[i] = max(cand, key=lambda r: r.bbox[2] + r.bbox[3]).text.strip()
    # (5) The set's own list of drawings (a "reference drawings" table printed on its sheets) gives the number's
    # shape, dashes included ("D310-4802-12J-0027-01"): a scan's read of the sheet's number that lost dashes
    # ("D3104802-12J0028-01") but has the same letters and digits in the same places is that number with the dashes
    # put back.
    if doc is not None:

        def cls(t: str) -> str:
            return re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", t))

        shapes = Counter()
        for sh in doc.sheets:
            for r in sh.runs:
                t = r.text.replace(" ", "").rstrip(".,|")
                if r.conf >= 0.9 and re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+){3,}", t):
                    shapes["-".join(cls(x) for x in t.split("-"))] += 1
        if shapes:
            shape, c = shapes.most_common(1)[0]
            parts = shape.split("-")
            flat = "".join(parts)
            if c >= 3:
                for i, n in enumerate(nums):
                    m = n.replace("=", "-")
                    if m != n and "-".join(cls(x) for x in m.split("-")) == shape:
                        renames[i] = m
                        continue
                    if (
                        "-".join(cls(x) for x in m.split("-")) != shape
                        and len(m.replace("-", "")) == len(flat)
                        and cls(m.replace("-", "")) == flat
                        and re.fullmatch(r"[A-Z0-9-]+", m)
                    ):
                        raw, out = m.replace("-", ""), []
                        pos = 0
                        for pt in parts:
                            out.append(raw[pos : pos + len(pt)])
                            pos += len(pt)
                        renames[i] = "-".join(out)
                for i, n in enumerate(
                    nums
                    # the sheet's own number printed with its dashes lost ("AB60S00015" for "AB-60-S-0001-5"), the
                    # number it
                    # carries beside a label
                ):
                    if i in renames or "-".join(cls(x) for x in n.split("-")) == shape or i >= len(doc.sheets):
                        continue
                    for r in doc.sheets[i].runs:
                        raw = r.text.replace(" ", "")
                        if (
                            r.conf >= 0.9
                            and is_horizontal(r)
                            and len(raw) == len(flat)
                            and cls(raw) == flat
                            and raw.isalnum()
                            and any(
                                re.sub(r"[^A-Z]", "", o.text.upper()).endswith(
                                    ("DWGNUMBER", "DWGNO", "DRAWINGNUMBER", "DRAWINGNO")
                                )
                                and o.bbox[2] <= r.bbox[0] + 2
                                and abs(o.center[1] - r.center[1]) <= 0.8 * r.size
                                for o in doc.sheets[i].runs
                            )
                        ):
                            pos, out = 0, []
                            for pt in parts:
                                out.append(raw[pos : pos + len(pt)])
                                pos += len(pt)
                            renames[i] = "-".join(out)
                            break
                conforming = sum(
                    "-".join(cls(x) for x in renames.get(i, n).split("-")) == shape for i, n in enumerate(nums)
                )
                if conforming >= 3:
                    for i, n in enumerate(nums):
                        if i not in renames and "-".join(cls(x) for x in n.split("-")) != shape and len(n) <= 4:
                            renames[i] = (
                                # a short mark (a project's "L10") among sheets that all carry the long document number
                                # is not this sheet's own
                                f"P{i + 1}"
                            )
    full = [n.split("-") for n in nums if re.fullmatch(r"[A-Z]{1,3}\d?(?:-[A-Z0-9]{1,5}){3,}", n)]
    if len(full) >= 4:
        width = Counter(len(t) for t in full).most_common(1)[0][0]
        full = [t for t in full if len(t) == width]
        lead: list[str] = []
        for i in range(width):
            tok, c = Counter(t[i] for t in full).most_common(1)[0]
            if c < 0.9 * len(full):
                break
            lead.append(tok)
        # the last parts are digits in every well-formed number
        digit_tail = [j for j in range(1, 3) if all(t[-j].isdigit() for t in full)]
        for i, n in enumerate(nums):
            if not lead or n in {"-".join(t) for t in full}:
                continue
            # a scan reads "4" as "/" and "0" as "C" / "O": mended where the scheme says the part is a digit (the shared
            # 12) or the tail is
            n = n.replace("/", "4") if all(c.isalnum() or c in "-/" for c in n) else n
            parts = [t for t in n.split("-") if t != ""]
            if len(parts) >= 3 and len(parts) + len(lead) >= width:
                for j in digit_tail:
                    if len(parts) >= j and j <= len(parts):
                        parts[-j] = (
                            parts[-j].translate(str.maketrans("COQDILBS", "00001185"))
                            if len(parts[-j]) == len(full[0][-j])
                            else parts[-j]
                        )
                n = "-".join(parts)
            if len(parts) < 3 or not re.fullmatch(r"[A-Z0-9]{1,5}(?:-[A-Z0-9]{1,5}){2,}", n.lstrip("-")):
                continue
            if "-".join(lead) in n:
                if len(parts) == width and n != nums[i]:
                    renames[i] = n
                continue
            for k in range(len(lead)):  # the parts that survived must continue the shared prefix
                if parts[: len(lead) - k] != lead[k:]:
                    continue
                if len(parts) + k == width and all(len(t) == len(u) for t, u in zip(parts, full[0][k:], strict=False)):
                    renames[i] = "-".join(lead[:k] + parts)
                break
    shaped = Counter()
    for n in nums:
        if re.fullmatch(r"[A-Z]\d{3}", n):
            shaped[n[0]] += 1
    if sum(shaped.values()) >= 3:
        for i, n in enumerate(nums):
            if re.fullmatch(r"\d{4}", n) and _DIGIT_FOR_LETTER.get(n[0]) in shaped:
                renames[i] = _DIGIT_FOR_LETTER[n[0]] + n[1:]
    # "S-2.1": a series with a letter, a dash and the sheet's own digits
    dashed = Counter(n[0] for n in nums if re.fullmatch(r"[A-Z]-\d+(?:\.\d+)?", n))
    if sum(dashed.values()) >= 3:
        for i, n in enumerate(nums):
            if re.fullmatch(r"\d-\d+(?:\.\d+)?", n) and _DIGIT_FOR_LETTER.get(n[0]) in dashed:
                renames[i] = _DIGIT_FOR_LETTER[n[0]] + n[1:]
    # (3) A number that is not well-formed between two consecutive neighbours of one series ("BC04" between B003 and
    # B005, "3006" between B006 and B008): the number the neighbours imply, when the read is at most two characters
    # away from it.
    cur = [renames.get(i, n) for i, n in enumerate(nums)]  # the neighbours as repaired above ("3005" -> "B005")
    for i in range(1, len(nums) - 1):
        a_, n_, b_ = cur[i - 1], nums[i], cur[i + 1]
        ma, mb = re.fullmatch(r"([A-Z])(\d{3})", a_), re.fullmatch(r"([A-Z])(\d{3})", b_)
        if (
            ma
            and mb
            and ma[1] == mb[1]
            and int(mb[2]) - int(ma[2]) == 2
            and len(n_) == 4
            and not re.fullmatch(r"[A-Z]\d{3}", n_)
            and re.fullmatch(r"[A-Z0-9]{4}", n_)
        ):
            pred = f"{ma[1]}{int(ma[2]) + 1:03d}"
            if sum(x != y for x, y in zip(n_, pred, strict=False)) <= 2 and pred not in cur:
                renames[i] = pred
    taken = set(nums)
    for i, new in renames.items():
        old = nums[i]
        if new in taken:
            continue
        taken.add(new)
        idx.sheets[i].number = new
    ren = {nums[i]: new for i, new in renames.items() if idx.sheets[i].number == new}
    for f in idx.facts:
        if f.sheet in ren:
            old, new = f.sheet, ren[f.sheet]
            f.sheet = new
            if f.id.startswith(old + "."):
                f.id = new + f.id[len(old) :]
            f.links = [new + link[len(old) :] if link.startswith(old + ".") else link for link in f.links]


def flag_label_misreads(idx: Index) -> None:
    """Convention: a set uses a few dozen member sizes, many times each. On a scan, a designation seen once or twice
    that differs by one character from one seen at least five times as often ("W200X35" beside 447 x "W200X36") is
    most likely that member misread, so it is flagged (`suspect_of`), never changed: an engineer may really have drawn
    the odd one."""

    def key(f):
        return f.attrs.get("section", f.value).upper().replace(" ", "")

    cnt = Counter(key(f) for f in idx.by_kind("label"))

    def one_off(a: str, b: str) -> bool:
        if abs(len(a) - len(b)) > 1 or a == b:
            return False
        if len(a) == len(b):
            return sum(x != y for x, y in zip(a, b, strict=False)) == 1
        if len(a) > len(b):
            a, b = b, a
        return any(b[:i] + b[i + 1 :] == a for i in range(len(b)))

    common = [t for t, c in cnt.items() if c >= 6]
    near: dict[str, str] = {}
    for sec, c in cnt.items():
        if c <= 2:
            hit = next((t for t in sorted(common, key=lambda t: -cnt[t]) if cnt[t] >= 5 * c and one_off(sec, t)), None)
            if hit:
                near[sec] = hit
    for f in idx.by_kind("label"):
        if key(f) in near:
            f.attrs["suspect_of"] = near[key(f)]
