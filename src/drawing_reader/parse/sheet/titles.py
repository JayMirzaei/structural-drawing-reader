"""Sheet-title readers used when the title is not simply the large text beside the sheet number."""

from __future__ import annotations

import difflib
import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.layout import is_horizontal, x_overlap
from drawing_reader.parse.revision_text import RE_DATE, RE_REV_CODE
from drawing_reader.parse.scale import RE_SCALE_BARE, normalise_scale
from drawing_reader.parse.sheet.base import SheetParserBase
from drawing_reader.parse.sheet_numbers import RE_SHEET_NO
from drawing_reader.parse.titleblock_fields import TITLEBLOCK_KEY_ALIASES, fuzzy_label_line, is_label_text
from drawing_reader.parse.titles import (
    RE_NOT_TITLE,
    RE_NOTE_LINE,
    RE_OCR_JUNK,
    RE_TITLE_WORD,
    is_caps,
    plausible_title,
    split_glued_title,
)


class TitleMixin(SheetParserBase):
    """Fallback readers for the sheet title: a labelled block, a vertical strip, an unlabelled stack."""

    def _title_fallback(
        self, common_large_texts: set[str], sheet_no, foot_only: bool = False, extra: bool = False
    ) -> None:
        """Sheet title when the large-text rule found none: stacked same-size capital lines in the title block that
        name a drawing type, nearest the sheet number. A block with no drawing-type word is taken only when it sits
        right beside the sheet number -- a blank title is better than a wrong one."""
        src = self.tb
        # a title set above the band, in the sheet number's own column (a stacked title block taller than the band)
        if extra:
            if sheet_no is None:
                return
            src = [
                r
                for r in self.s.runs
                if r not in self.tb
                and sheet_no.bbox[0] - 6 * sheet_no.size <= r.bbox[0] <= sheet_no.bbox[0] + 0.5 * sheet_no.size
                and 0 < sheet_no.bbox[1] - r.bbox[3] <= min(0.2 * self.s.height, 4 * sheet_no.size)
            ]
        pool = [
            r
            for r in src
            if is_horizontal(r)
            and r.conf >= 0.8
            and r is not sheet_no
            and r.text not in common_large_texts
            and sum(c.isalpha() for c in r.text) >= 3
            and not RE_SHEET_NO.match(r.text.replace(" ", ""))
            and not RE_DATE.search(r.text)
            and not RE_NOT_TITLE.search(r.text)
            and ":" not in r.text
            and not is_label_text(r.text)
            and sum(c.isdigit() for c in r.text) <= len(r.text) // 3
            and re.sub(r"[^a-z0-9]", "", r.text.lower()) not in self.repeated
            and not RE_SCALE_BARE.match(normalise_scale(r.text))
            and not RE_NOTE_LINE.match(r.text)
            and len(r.text.split()) <= 9
            and not RE_REV_CODE.match(r.text.strip())
            and not (self.is_scan and fuzzy_label_line(r.text))
        ]
        if not pool:
            return
        pool.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        blocks: list[list[TextRun]] = []
        for r in pool:
            for b in blocks:
                bot = max(b, key=lambda o: o.bbox[3])
                # a scan's boxes are padded: stacked lines overlap
                if (
                    abs(r.size - b[0].size) <= 0.25 * b[0].size
                    and x_overlap(bot.bbox, r.bbox) > 0
                    and is_caps(r.text) == is_caps(b[0].text)
                    and -(1.3 if self.is_scan else 0.5) * r.size <= r.bbox[1] - bot.bbox[3] <= 0.9 * r.size
                ):
                    b.append(r)
                    break
            else:
                blocks.append([r])

        def score(b: list[TextRun]) -> float:
            # a scan's "STRUCTURALGENERALNOTES" still names a drawing type
            text = split_glued_title(" ".join(o.text for o in b))
            letters = [c for c in text if c.isalpha()]
            sc = 3.0 if RE_TITLE_WORD.search(text) else 0.0
            sc += 1.0 if letters and sum(c.isupper() for c in letters) >= 0.8 * len(letters) else 0.0
            sc += 1.0 if len(text.split()) >= 2 else 0.0
            # nine or more words with lower-case letters is a drawing note's sentence, not a title
            sc -= 3.0 if len(text.split()) >= 9 and any(c.islower() for c in text) else 0.0
            if sheet_no is not None:
                x0, y0 = min(o.bbox[0] for o in b), min(o.bbox[1] for o in b)
                x1, y1 = max(o.bbox[2] for o in b), max(o.bbox[3] for o in b)
                gap = max(0.0, sheet_no.bbox[0] - x1, x0 - sheet_no.bbox[2]) + max(
                    0.0, sheet_no.bbox[1] - y1, y0 - sheet_no.bbox[3]
                )
                sc += 2.0 if gap <= 6 * sheet_no.size else 1.0 if gap <= 14 * sheet_no.size else 0.0
            return sc

        # equal scores: the bigger type is the title, a small block is a reference table
        best = max(blocks, key=lambda b: (score(b), max(o.size for o in b)))
        has_word = bool(RE_TITLE_WORD.search(split_glued_title(" ".join(o.text for o in best))))
        if score(best) < 5 or not (has_word or (sheet_no is not None and score(best) >= 6)):
            return
        # a line printed in two runs on one row ("NORTH BAY" + "- ROOF FRAMING PLAN"): the neighbour on the same row
        # joins
        for o in pool:
            if o not in best and any(
                abs(o.size - m.size) <= 0.25 * m.size
                and abs(o.center[1] - m.center[1]) <= 0.4 * m.size
                and -0.3 * m.size <= o.bbox[0] - m.bbox[2] <= 2.0 * m.size
                for m in best
            ):
                best.append(o)
        unit = 0.6 * min(o.size for o in best)  # one divisor for every line: a title's lines differ a little in size
        best.sort(key=lambda o: (round(o.center[1] / unit), o.bbox[0]))
        if foot_only and len(best) > 3:
            # a long stack is project / client lines over the title: the foot line is this sheet's own
            best = [max(best, key=lambda o: o.bbox[3])]
        title = " ".join(o.text.strip() for o in best)
        self.meta.title = title
        self.title_src = "fallback"
        self._add(
            "titleblock",
            title,
            (
                min(o.bbox[0] for o in best),
                min(o.bbox[1] for o in best),
                max(o.bbox[2] for o in best),
                max(o.bbox[3] for o in best),
            ),
            title,
            conf=0.7,
            field="sheet_title",
        )
        self.used.update(o.id for o in best)

    def _title_from_label(self, sheet_no) -> None:
        """A "TITLE" / "DRAWING TITLE" label in the bottom band, wherever the title-block box edge was found (a scan's
        box can start right of the title cell): its value is the block of lines beside or under it. Sets the "Sheet
        Title" field (read by `parse_titleblock`)."""
        tbids = {id(r) for r in self.tb}
        # a right-hand strip block reaches above the bottom band
        pool = [
            r
            for r in self.s.runs
            if is_horizontal(r)
            and (
                r.bbox[1] >= self.band - 2
                or id(r) in tbids
                or (r.bbox[0] >= 0.7 * self.s.width and r.bbox[1] >= 0.4 * self.s.height)
            )
        ]
        for lab in pool:
            key = lab.text.strip().rstrip(":.# ").upper()
            letters = re.sub(r"[^A-Z]", "", key)
            # a scan's misspelling of "DRAWING TITLE:"
            if (
                TITLEBLOCK_KEY_ALIASES.get(key, key) != "SHEET TITLE"
                and letters not in ("TITLE", "DRAWINGTITLE", "SHEETTITLE", "SUBJECT", "SUBJECTSUJET", "TITLETITRE")
                and not (
                    self.is_scan
                    and lab.conf < 1.0
                    and len(letters) >= 7
                    and difflib.SequenceMatcher(None, letters, "DRAWINGTITLE").ratio() >= 0.75
                )
            ):
                continue
            # a neighbouring caption ("JOB NUMBER :") is no value
            cands = [
                o
                for o in pool
                if o is not lab
                and o.bbox[0] >= lab.bbox[2] - 2
                and o.bbox[0] - lab.bbox[2] < 120
                and abs(o.center[1] - lab.center[1]) <= 0.8 * o.size
                and sum(c.isalpha() for c in o.text) >= 3
                and not is_label_text(o.text)
                and not o.text.rstrip().endswith(":")
            ]
            first = min(cands, key=lambda o: o.bbox[0]) if cands else None
            if first is None:
                below = [
                    o
                    for o in pool
                    if o is not lab
                    and 0 <= o.bbox[1] - lab.bbox[3] <= 2.5 * max(lab.size, o.size)
                    and x_overlap(lab.bbox, o.bbox) > 0
                    and sum(c.isalpha() for c in o.text) >= 3
                    and not is_label_text(o.text)
                ]
                first = min(below, key=lambda o: o.bbox[1]) if below else None
            if first is None:
                continue
            stack = self._title_stack(first, pool, sheet_no)
            keep = self._drop_repeated_head(stack)  # project / client lines repeat on every sheet
            # a line the scan could not read ("STAIR N0? 1 PLRNS") is left out, the rest stays
            keep = [o for o in keep if not RE_OCR_JUNK.search(o.text)] or keep[-1:]
            # a long block carries the project name above the title: shorten from the top until it reads as a title
            for n in (
                len(keep),
                2,
                1,
            ):
                lines = keep[-n:]
                text = " ".join(o.text.strip() for o in lines).replace("_", " ")
                if plausible_title(text, frozenset(), one_word_ok=True):
                    self.meta.fields["Sheet Title"] = text
                    self.used.update(o.id for o in stack)
                    self._title_label_stack = lines
                    return

    def _title_from_unlabelled_stack(self, sheet_no) -> None:
        """A scan's title block with no TITLE label: under the field rows (JOB NO., DATE, SCALE, SH.NO.) a stack of
        lines runs to the foot of the block -- client, project, then this sheet's own title -- and a plot stamp (date
        / time / file path) closes it. The lines printed on most sheets are the client and project; what is left at
        the foot of the stack is the title."""
        field_words = (
            "JOBNO",
            "DRAWNBY",
            "DATE",
            "SCALE",
            "SHNO",
            "SHEETNO",
            "CHECKED",
            "PROJECTNO",
            "DWGNO",
            "DRAWINGNO",
            "ISSUE",
        )
        tb = [r for r in self.tb if is_horizontal(r)]
        labels = [r for r in tb if re.sub(r"[^A-Z]", "", r.text.upper()) in field_words and len(r.text) <= 14]
        if len(labels) < 3:
            return
        # the field labels share one left edge; a stray "Date" elsewhere does not
        col = max(labels, key=lambda r: sum(1 for o in labels if abs(o.bbox[0] - r.bbox[0]) <= 0.6 * r.size))
        labels = [o for o in labels if abs(o.bbox[0] - col.bbox[0]) <= 1.5 * col.size] or labels
        if len(labels) < 3:
            return
        y_label = max(r.bbox[3] for r in labels)
        x0 = min(r.bbox[0] for r in labels) - 0.5 * max(r.size for r in labels)

        def stamp(t):
            # not "1:40", a scale
            return bool(re.search(r"\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}\s*[AP]M|\.dwg|\|", t, re.I))

        stamps = [
            r for r in tb if r.bbox[1] >= y_label - 1 and r.bbox[0] >= x0 and (stamp(r.text) or RE_DATE.search(r.text))
        ]
        # the plot stamp and everything on its row
        pool = [
            r
            for r in tb
            if r.bbox[1] >= y_label - 1
            and r.bbox[0] >= x0
            and not is_label_text(r.text)
            and re.search(r"[A-Za-z]{3}", r.text)
            and r is not sheet_no
            and not any(abs(o.center[1] - r.center[1]) <= 0.6 * max(o.size, r.size) for o in stamps)
        ]
        if not pool:
            return
        pool.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        lines: list[list[TextRun]] = []
        for r in pool:
            for ln in lines:
                if abs(ln[0].center[1] - r.center[1]) <= 0.4 * r.size:
                    ln.append(r)
                    break
            else:
                lines.append([r])
        texts = [" ".join(o.text.strip() for o in sorted(ln, key=lambda o: o.bbox[0])) for ln in lines]
        keys = [re.sub(r"[^a-z0-9]", "", t.lower()) for t in texts]
        # the last line is the title, even when several sheets share it ("ELEVATIONS AND DETAILS" on half of them)
        keep = [texts[-1]]
        for t, k in zip(reversed(texts[:-1]), reversed(keys[:-1]), strict=False):
            if k in self.repeated or len(keep) >= 3:
                break
            keep.insert(0, t)  # a title of several lines: the lines above it that are not project / client lines
        text = split_glued_title(" ".join(keep))
        if plausible_title(text, frozenset(), one_word_ok=True):
            self.meta.fields["Sheet Title"] = text
            for ln in lines:
                self.used.update(o.id for o in ln)

    def _title_from_vertical_label(self) -> None:
        """A title strip written up the side of the sheet (text rotated 90 deg, reading bottom to top): the "DRAWING
        TITLE:" label and its value are vertical runs, the value in the column just right of the label (the next line
        "down" in the rotated frame), overlapping it along y."""
        vert = [r for r in self.s.runs if abs(r.dir[0]) < 0.1 and abs(r.dir[1]) > 0.9]
        for lab in vert:
            key = lab.text.strip().rstrip(":.# ").upper()
            # rotated text loses its spaces
            if TITLEBLOCK_KEY_ALIASES.get(key, key) != "SHEET TITLE" and key.replace(" ", "") not in (
                "TITLE",
                "DRAWINGTITLE",
                "SHEETTITLE",
            ):
                continue
            sign = 1 if lab.dir[1] < 0 else -1  # reading upward: the next line is to the right; downward: to the left

            def col_gap(o, ref):
                return (o.bbox[0] - ref.bbox[2]) if sign > 0 else (ref.bbox[0] - o.bbox[2])

            def below(ref, size):
                return [
                    o
                    for o in vert
                    if o is not lab
                    and o is not ref
                    and -0.6 * size <= col_gap(o, ref) <= 1.6 * size
                    and min(o.bbox[3], ref.bbox[3]) - max(o.bbox[1], ref.bbox[1]) > 0
                    and abs(o.size - size) <= 0.3 * size
                    and sum(c.isalpha() for c in o.text) >= 3
                    and not is_label_text(o.text)
                    and not RE_NOT_TITLE.search(o.text)
                    and ":" not in o.text
                    and not RE_REV_CODE.match(o.text.strip())
                ]

            first = [
                o
                for o in vert
                if o is not lab
                and -0.6 * lab.size <= col_gap(o, lab) <= 2.0 * max(lab.size, o.size)
                and min(o.bbox[3], lab.bbox[3]) - max(o.bbox[1], lab.bbox[1]) > 0
                and sum(c.isalpha() for c in o.text) >= 3
                and not is_label_text(o.text)
                and ":" not in o.text
            ]
            if not first:
                continue
            first = min(first, key=lambda o: col_gap(o, lab))
            stack = [first]
            while len(stack) < 6 and (nxt := below(stack[-1], first.size)):
                stack.append(min(nxt, key=lambda o: col_gap(o, stack[-1])))
            text = split_glued_title(" ".join(o.text.strip() for o in stack))
            if plausible_title(text, frozenset(), one_word_ok=True):
                self.meta.fields["Sheet Title"] = text
                self.used.update(o.id for o in stack)
                return

    def _drop_repeated_head(self, stack: list) -> list:
        """The title lines of a block without the project / client lines above them: lines printed on most sheets are
        dropped from the top, but the last two stay -- a series of sheets that share a sub-title ("EAST WING (PHASE
        2A) FRAMING") repeats it too, and it is part of the title."""
        keep = list(stack)
        while len(keep) > 2 and re.sub(r"[^a-z0-9]", "", keep[0].text.lower()) in self.repeated:
            keep.pop(0)
        return keep

    def _title_stack(self, first, runs, sheet_no) -> list:
        """The lines of a title written as a block under a "TITLE" label: runs of the first line's size, each directly
        below the last and overlapping it in x (centred or left-aligned lines), ending at a label, a small field or a
        gap."""

        def row_of(run) -> list:
            """The run and the runs of its own printed line a scan cut it from ("AB120-04A -" | "PLAN & SECTIONS"), left
            to right."""
            mates = [
                o
                for o in runs
                if o is not run
                and o is not sheet_no
                and abs(o.size - run.size) <= 0.2 * run.size
                and abs(o.center[1] - run.center[1]) <= 0.4 * run.size
                and -0.5 * run.size <= max(o.bbox[0] - run.bbox[2], run.bbox[0] - o.bbox[2]) <= run.size
                and re.search(r"[A-Za-z0-9]", o.text)
                and not is_label_text(o.text)
                and not RE_REV_CODE.match(o.text.strip())
            ]
            return sorted([run] + mates, key=lambda o: o.bbox[0])

        row = row_of(first)
        stack = list(row)
        while len(stack) < 8:
            nxt = [
                o
                for o in runs
                if o not in stack
                and o is not sheet_no
                and abs(o.size - first.size) <= 0.2 * first.size
                and any(
                    -0.3 * first.size <= o.bbox[1] - last.bbox[3] <= 0.9 * first.size
                    and x_overlap(last.bbox, o.bbox) > 0
                    for last in row
                )
                and re.search(r"[A-Za-z]{3,}", o.text)
                and not is_label_text(o.text)
                and not RE_NOT_TITLE.search(o.text)
                and ":" not in o.text
                and sum(c.isdigit() for c in o.text) <= len(o.text) // 4
                and not RE_SHEET_NO.match(o.text.replace(" ", ""))
                and not RE_REV_CODE.match(o.text.strip())
                and not fuzzy_label_line(o.text)
            ]
            if not nxt:
                break
            row = row_of(min(nxt, key=lambda o: o.bbox[1]))
            stack.extend(o for o in row if o not in stack)
        return stack
