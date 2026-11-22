"""General notes, material clauses, sheet references in text, design-load tables and leftover text."""

from __future__ import annotations

import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.dimension_values import RE_NUMBER
from drawing_reader.parse.layout import is_horizontal, run_orientation
from drawing_reader.parse.materials import RE_ASTM, RE_FY, RE_FY_MAX, RE_SIZE, prose_yield_mpa, spec_role
from drawing_reader.parse.note_text import (
    RE_ALPHA_ITEM,
    RE_BULLET,
    RE_BULLET_GLUED,
    RE_CRITERIA_LABEL,
    RE_FACTOR_VALUE,
    RE_FIELD_HEADING,
    RE_ITEM_GLUED,
    RE_ITEM_NO,
    RE_LOAD_LABEL,
    RE_LOAD_VALUE,
    RE_STRIP_BOILERPLATE,
    heading_case,
    reads_like_strip_note,
    split_numbered_items,
)
from drawing_reader.parse.revision_text import RE_DATE
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.parse.sheet_numbers import RE_DETAIL_REF, RE_SHEET_REF, RE_SHEET_TOKEN
from drawing_reader.parse.titleblock_fields import is_label_text
from drawing_reader.parse.titles import RE_NOT_TITLE
from drawing_reader.schema import Fact


class NotesMixin(SheetParserBase):
    """Reads note text: headings, numbered items, the material and reference facts inside them."""

    def parse_load_table(self) -> None:
        """Convention: a load-criteria table states a label ('LIVE LOAD', 'DEAD LOAD') and its value ('1.9 kPa') as
        two separate text runs, unlike the 'NAME = value' form (`RE_PARAM` in `qa.rules.loads`), so a keyword search
        would only ever surface the label, never the number. The value sits to the label's right on some templates and
        below-and-right on others, so both `_right_of` and `_below_label` are tried, as the title-block key/value
        pairing does. Tagged with attrs so `rule_loads` can match them directly without a text-pattern regex over
        `source_text`. Runs before `parse_notes`/`parse_dimensions` so the label and value runs are claimed here, not
        swept into an unrelated generic note or dimension fact."""
        for r in self.body:
            if r.id in self.used or not is_horizontal(r):
                continue
            lab = r.text.strip().rstrip(":")
            criteria = not RE_LOAD_LABEL.match(lab) and bool(RE_CRITERIA_LABEL.match(lab))
            if not RE_LOAD_LABEL.match(lab) and not criteria:
                continue
            v = self._right_of(r, self.body) or self._below_label(r, self.body)
            if not v or v.id in self.used:
                continue
            m = RE_LOAD_VALUE.match(v.text.strip())
            if not m and criteria and re.search(r"FACTOR", lab):
                m = RE_FACTOR_VALUE.match(v.text.strip())  # an importance factor is dimensionless: "1.0 (NORMAL)"
            if not m:
                continue
            label = r.text.strip().rstrip(":")
            bbox = (r.bbox[0], min(r.bbox[1], v.bbox[1]), v.bbox[2], max(r.bbox[3], v.bbox[3]))
            self._add(
                "note",
                f"{label} {v.text.strip()}",
                bbox,
                f"{r.text} {v.text}",
                conf=0.85,
                param_name=label,
                param_value=m.group(1),
                param_unit=(m.group(2) if m.lastindex and m.lastindex >= 2 else "") or "",
            )
            self.used.update({r.id, v.id})

    def parse_notes(self) -> None:
        """Convention: note headings are ALL CAPS ending with ':'; items are numbered '1.' or bulleted and
        may wrap over several lines in the same column. PDF paragraph blocks are split at every item start."""
        # Notes also sit in the title-block strip (a side column of general notes, a bottom-band note): those runs are
        # read too, but only text that is plainly a note -- long, not a label/value field, not legal or per-sheet
        # boilerplate (see `_is_strip_note`).
        tb_notes = [r for r in self.tb if is_horizontal(r) and r.id not in self.used and self._is_strip_note(r)]
        tb_ids = {id(r) for r in tb_notes}
        runs = [r for r in self.body if is_horizontal(r) and r.id not in self.used] + tb_notes
        blocks: dict[int, list[TextRun]] = {}
        for r in runs:
            blocks.setdefault(r.block, []).append(r)
        paras = []
        for rs in blocks.values():
            rs.sort(key=lambda r: (round(r.bbox[1]), r.bbox[0]))
            bx0 = min(r.bbox[0] for r in rs)
            cur: list[TextRun] = []
            for r in rs:
                t = r.text.strip()
                starts_item = bool(
                    RE_ITEM_NO.match(t)
                    or RE_ALPHA_ITEM.match(t)
                    or RE_BULLET.match(t)
                    and len(t) <= 2
                    or RE_ITEM_GLUED.match(t)
                    or RE_BULLET_GLUED.match(t)
                )
                is_heading = (
                    t.endswith(":")
                    and t.upper() == t
                    and len(t) < 64
                    and r.bbox[0] <= bx0 + 3
                    and len(t.split()) <= 8
                    or self._is_scan_heading(t, r)
                ) and not RE_FIELD_HEADING.match(t.rstrip(":").strip())
                starts_kv = bool(re.match(r"^[A-Z][A-Z .&/\-]{1,30}:\s*\S", t)) and r.bbox[0] <= bx0 + 3
                if (
                    cur
                    and (starts_item or is_heading or starts_kv)
                    and not (len(cur) == 1 and (RE_ITEM_NO.match(cur[0].text) or RE_ALPHA_ITEM.match(cur[0].text)))
                ):
                    paras.append(cur)
                    cur = []
                cur.append(r)
                if is_heading:
                    paras.append(cur)
                    cur = []
            if cur:
                paras.append(cur)
        items = []
        for rs in paras:
            number = ""
            first = rs[0].text.strip()
            if len(rs) > 1 and (
                RE_ITEM_NO.match(first) or RE_ALPHA_ITEM.match(first) or (RE_BULLET.match(first) and len(first) <= 2)
            ):
                number = first.rstrip(".)") if (RE_ITEM_NO.match(first) or RE_ALPHA_ITEM.match(first)) else "•"
                body_runs = rs[1:]
            else:
                body_runs = rs
            text = " ".join(r.text for r in body_runs).strip()
            bbox = (
                min(r.bbox[0] for r in rs),
                min(r.bbox[1] for r in rs),
                max(r.bbox[2] for r in rs),
                max(r.bbox[3] for r in rs),
            )
            items.append({"text": text, "bbox": bbox, "runs": rs, "number": number, "size": rs[0].size})
        items.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]))
        headings = []  # (heading_title, bbox)
        for p in items:
            t = p["text"]
            if (
                t.endswith(":")
                and t.upper() == t
                and len(t) < 64
                and not p["number"]
                and len(t.split()) <= 8
                or len(p["runs"]) == 1
                and self._is_scan_heading(t, p["runs"][0])
            ) and not RE_FIELD_HEADING.match(t.rstrip(":").strip()):
                h = heading_case(t.rstrip(":"))
                f = self._add("note", t, p["bbox"], t, conf=0.9, heading=h, role="heading")
                headings.append((h, f.bbox))
                for r in p["runs"]:
                    self.used.add(r.id)
        for p in items:
            t = p["text"]
            if not t or (t.endswith(":") and t.upper() == t and len(t) < 64 and not p["number"]):
                continue
            if len(p["runs"]) == 1 and self._is_scan_heading(t, p["runs"][0]):
                continue
            words = [w for w in t.split() if re.search(r"[A-Za-z]{2,}", w)]
            m_num = re.match(r"^(\d{1,2})[.)]\s+(.*)$", t) or RE_ITEM_GLUED.match(t)
            m_bul = None if (p["number"] or m_num) else RE_BULLET_GLUED.match(t)
            number = p["number"] or (m_num.group(1) if m_num else ("•" if m_bul else ""))
            body = m_num.group(2) if m_num else (m_bul.group(1) if m_bul else t)
            if not number and len(words) < 3:
                continue  # a short unnumbered line is a label or a stray word, not a note
            if number and not words and not re.search(r"[A-Za-z]{2,}", body):
                # "50" then "250" on one baseline are two dimensions of a string, not note 50 saying "250":
                # a note has words. The runs are left for the dimension reader.
                continue
            heading = self._heading_for(p["bbox"], headings)
            conf = 0.85 if (number and heading) else (0.7 if number or heading else 0.6)
            strip = {"in_titleblock": True} if all(id(r) in tb_ids for r in p["runs"]) else {}
            if strip and not number and (len(words) < 6 or not reads_like_strip_note(t)):
                # an unnumbered strip line is a note only if it reads like one (not a title line, path or garble)
                continue
            for num, text in split_numbered_items(number, body):
                f = self._add(
                    "note",
                    text,
                    p["bbox"],
                    t if text == body else text,
                    conf=conf,
                    heading=heading,
                    number=num,
                    **strip,
                )
                self._parse_material(f, text, heading)
                self._parse_refs(f, text)
            for r in p["runs"]:
                self.used.add(r.id)

    def _is_strip_note(self, r: TextRun) -> bool:
        """A title-block-strip run that reads as note text: five or more words, not a key/value field, not legal or
        per-sheet boilerplate, not a line repeated on most sheets."""
        t = r.text.strip()
        if len([w for w in t.split() if re.search(r"[A-Za-z]{2,}", w)]) < 3 or r.conf < 0.6:
            return False
        if RE_STRIP_BOILERPLATE.search(t) or RE_NOT_TITLE.search(t) or RE_DATE.search(t) or is_label_text(t):
            return False
        return re.sub(r"[^a-z0-9]", "", t.lower()) not in self.repeated

    def _is_scan_heading(self, t: str, run: TextRun) -> bool:
        """Convention (scans only): a note heading is a short ALL-CAPS line alone on its row, without a colon,
        ending in a heading word ("GENERAL NOTES", "MATERIALS", "DESIGN CRITERIA", "LEGEND"). Vector sheets keep
        the ':'-terminated rule only, so their baselines do not move."""
        if run.conf >= 1.0 or not t or t != t.upper() or any(c.isdigit() for c in t) or t.endswith(":"):
            return False
        return (
            sum(c.isalpha() for c in t) >= 4
            and len(t.split()) <= 4
            and t.split()[-1].strip(".")
            in (
                "NOTES",
                "NOTE",
                "SPECIFICATIONS",
                "REQUIREMENTS",
                "CRITERIA",
                "LOADS",
                "LEGEND",
                "ABBREVIATIONS",
                "DESIGN",
                "MATERIALS",
                "FABRICATION",
                "ERECTION",
                "CONSTRUCTION",
            )
        )

    def _heading_for(self, bbox, headings) -> str:
        """Nearest heading above the item in the same text column (heading x0 at/left of item x0)."""
        best, bd = "", 1e9
        scan = any(r.conf < 1.0 for r in self.s.runs[:30])
        for h, hb in headings:
            # a scan heading is often centred over its column, so its x0 can sit right of the items' x0
            same_col = (hb[0] <= bbox[0] + 5 and bbox[0] - hb[0] < 120) or (
                scan and min(hb[2], bbox[2]) - max(hb[0], bbox[0]) > 0.5 * (hb[2] - hb[0])
            )
            if hb[1] <= bbox[1] + 2 and same_col:
                d = bbox[1] - hb[1]
                if d < bd:
                    best, bd = h, d
        return best

    def _parse_material(self, note: Fact, body: str, heading: str | None) -> None:
        """A general-notes clause often cites several distinct standards in one paragraph (e.g. a
        lettered sub-list 'a. CSA S16 ... d. ASTM A653 ...'); one material fact per distinct spec
        keeps a later citation (a roof-deck galvanizing spec) from hiding an earlier, more relevant
        one (the steel-design code) behind a single fact that could only ever hold one spec."""
        specs = list(dict.fromkeys(m.group(1) for m in RE_ASTM.finditer(body)))
        fy = RE_FY.findall(body) or prose_yield_mpa(body)
        fy_max = RE_FY_MAX.findall(body)
        if not specs and not fy:
            return
        m = re.match(r"^([A-Z][A-Z .,&/\-]+?):\s*(.+)$", body)
        component = heading_case(m.group(1)) if m else (heading or "")
        # Convention: a material clause writes the component's size ahead of its spec citation
        # (e.g. 'BOLT DIA.: 7/8" ASTM A325 U.N.O.') -- only look for a size token in the text before
        # the first spec citation, so a spec's own digits (e.g. 'A992') never get mistaken for a
        # size. When the fact is Fy=-only (no spec citation at all), scan the whole clause.
        astm_match = RE_ASTM.search(body)
        size_scope = body[: astm_match.start()] if astm_match else body
        size_match = RE_SIZE.search(size_scope)
        size = size_match.group(0).replace(" ", "") if size_match else ""
        # A clause can state several yields ("REBAR ... 400 MPa, BARS MARKED "W" ... 500 MPa"): the fact keeps the
        # first as fy_mpa and lists every distinct one in fy_all_mpa so answers can say there are several.
        fy_all = "/".join(dict.fromkeys(fy))
        for spec in specs or [""]:
            self._add(
                "material",
                body,
                note.bbox,
                note.source_text,
                conf=0.85,
                component=component,
                spec=spec,
                role=spec_role(spec),
                fy_mpa=fy[0] if fy else "",
                fy_max_mpa=fy_max[0] if fy_max else "",
                heading=heading or "",
                size=size,
                fy_all_mpa=fy_all if "/" in fy_all else "",
            )
            note.links.append(self.facts[-1].id)

    def _parse_refs(self, note: Fact, body: str) -> None:
        up = body.upper()
        for m in RE_SHEET_REF.finditer(up):
            toks = list(RE_SHEET_TOKEN.finditer(m.group(1)))
            # "SEE S700 SERIES FOR FRAMING" names a whole series (S701-S709), not a single sheet S700.
            if toks and re.match(r"\s*SERIES\b", up[m.end(1) :]):
                toks = toks[:-1]
            for tok in toks:
                target = f"S{tok.group(1) or '.'}{tok.group(2)}"  # as printed; an unseparated "S5" reads as "S.5"
                self._add("reference", target, note.bbox, body, conf=0.8, target_sheet=target, context=body[:120])
        for m in RE_DETAIL_REF.finditer(up):
            detail = m.group(1).upper()
            target = re.sub(r"\s", "", m.group(2).upper())
            self._add(
                "reference",
                f"{detail}/{target}",
                note.bbox,
                body,
                conf=0.8,
                target_sheet=target,
                detail=detail,
                context=body[:120],
            )

    def parse_remaining_text(self) -> None:
        """Anything not consumed by a rule is kept as a searchable text fact (low confidence).

        Includes `self.tb` (the title-block band), not just the drawing area (`self.body`): a run in that
        band that is not a title-block label or value (parse_titleblock marked those `used`) is kept too,
        because some templates put real content low on the page beside the title block, such as a
        design-criteria table with dotted leaders ("LIVE LOAD.....:3.6 kPa")."""
        for r in self.body + self.tb:
            if r.id in self.used or len(r.text) < 3:
                continue
            if RE_NUMBER.match(r.text):
                continue
            self._add("text", r.text, r, r.text, conf=0.5, orientation=run_orientation(r))
            self._parse_refs(self.facts[-1], r.text)
