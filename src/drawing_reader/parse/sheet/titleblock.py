"""Title block: sheet number, sheet title, key/value fields, sheet scale and project location."""

from __future__ import annotations

import re

from drawing_reader.ingest import TextRun
from drawing_reader.parse.layout import is_horizontal, same_row, x_overlap
from drawing_reader.parse.location import RE_LOC_ADDRESS, RE_LOC_LABEL, RE_LOC_LEGAL, find_city_region
from drawing_reader.parse.note_text import RE_ITEM_NO
from drawing_reader.parse.revision_text import RE_DATE, RE_REV_CODE, REV_TABLE_HEADER_WORDS, reads_like_a_note
from drawing_reader.parse.scale import (
    RE_SCALE_BARE,
    RE_SCALE_LABEL_ONLY,
    RE_SCALE_LABELLED,
    canonical_scale,
    normalise_scale,
)
from drawing_reader.parse.sheet.titles import TitleMixin
from drawing_reader.parse.sheet_numbers import (
    RE_DOC_NO,
    RE_DRAWING_NO,
    RE_SHEET_NO,
    document_number_text,
    fuzzy_number_label,
    is_page_count,
    join_split_numbers,
    labelled_number_ok,
)
from drawing_reader.parse.titleblock_fields import (
    NON_VALUE_WORDS,
    PLACEHOLDER_VALUES,
    RE_PROJNO_INLINE,
    SHEET_ID_KEYS,
    TITLEBLOCK_KEY_ALIASES,
    TITLEBLOCK_KEYS,
    fuzzy_label_line,
    plausible_project_no,
)
from drawing_reader.parse.titles import (
    RE_FIELD_ROW,
    RE_OCR_JUNK,
    RE_SHEET_OF,
    fix_title_digits,
    plausible_title,
    split_glued_title,
    trim_stray_labels,
)

_WIDEN = object()  # returned by _find_sheet_number: widen the title-block region and parse again


def _is_titleblock_label(r) -> bool:
    """A run whose own text is a title-block label ("SHEET NUMBER", "PROJECT NUMBER") can never be a title's value.

    On templates where a label is set at the size of its value, the cross-sheet `common_large_texts` count does not
    reliably catch it, so it could otherwise win the proximity guess for the title."""
    k = r.text.rstrip(":.# ").upper()
    return TITLEBLOCK_KEY_ALIASES.get(k, k) in TITLEBLOCK_KEYS


class TitleBlockMixin(TitleMixin):
    """Reads the title block of a sheet."""

    def parse_location(self) -> None:
        """Where the project is (see RE_LOC_*). One "titleblock" fact per find, field "Location", attrs: loc_kind =
        label | address | city_province | legal_land, size (text height), in_titleblock. An address is joined to the
        "City, Province" line beside or below it. Looked for on the whole sheet, not only the title block: client and
        project addresses are printed in a title strip, a corner stamp or a big heading, depending on the template. A
        scan's text must be confident (0.6+)."""
        runs = [r for r in self.tb + self.body if is_horizontal(r) and r.conf >= 0.6 and len(r.text) <= 90]
        tb_ids = {id(r) for r in self.tb}
        for r in runs:
            t = r.text.replace("\xa0", " ").strip()
            extra = dict(field="Location", size=round(r.size, 1), in_titleblock=id(r) in tb_ids)
            m = RE_LOC_LABEL.match(t)
            if m:
                v = m.group(1).strip() if m.group(1) else None
                cand = None if v else (self._right_of(r, runs) or self._below_label(r, runs))
                text = v or (cand.text.strip() if cand is not None else "")
                if len(text) >= 4 and any(c.isalpha() for c in text) and not RE_LOC_LABEL.match(text):
                    self._add(
                        "titleblock",
                        text,
                        cand or r,
                        t + (" " + text if cand is not None else ""),
                        conf=0.85,
                        loc_kind="label",
                        **extra,
                    )
                continue
            m = RE_LOC_ADDRESS.search(t)
            if m:
                value = re.sub(r"\s+", " ", m.group(0).strip())
                place = find_city_region(t[m.end() :])
                if place is None:
                    nxt = self._below(r, runs, 1.6) or self._right_of(r, runs, 60)
                    place = find_city_region(nxt.text.replace("\xa0", " ")) if nxt is not None else None
                if place:
                    value += f", {place[0]}, {place[1]}"
                self._add("titleblock", value, r, t, conf=0.7, loc_kind="address", **extra)
                continue
            m = RE_LOC_LEGAL.search(t)
            if m:
                self._add(
                    "titleblock",
                    re.sub(r"\s+", "", m.group(0)).upper(),
                    r,
                    t,
                    conf=0.75,
                    loc_kind="legal_land",
                    **extra,
                )
                continue
            place = find_city_region(t)
            if place:
                self._add("titleblock", f"{place[0]}, {place[1]}", r, t, conf=0.65, loc_kind="city_province", **extra)

    def parse_sheet_scale(self) -> None:
        """Sheet scale when the title-block label/value pairing found none (parse_titleblock). Candidates: a run
        stating "SCALE: <value>", a lone "SCALE" label with its value beside/below, and -- title block only -- a bare
        value. Several different values on one sheet means per-view scales: leave the sheet scale empty and let the
        views carry theirs."""
        if self.meta.scale:
            return
        tb_ids = {id(r) for r in self.tb}
        runs = [r for r in self.tb + self.body if is_horizontal(r)]
        labelled: list[tuple[TextRun, str]] = []
        bare: list[tuple[TextRun, str]] = []
        for r in runs:
            t = normalise_scale(r.text)
            if len(t) > 40:
                continue
            m = RE_SCALE_LABELLED.match(t)
            if m:
                labelled.append((r, canonical_scale(m.group(1), exact=r.conf >= 1.0)))
                continue
            if RE_SCALE_LABEL_ONLY.match(t):
                # beside the label first, then under it: the run beside may be the next field's label ("DRAWING NO"),
                # not a value
                v, vm = None, None
                for cand in (self._right_of(r, runs, 150), self._below_label(r, runs)):
                    m2 = RE_SCALE_BARE.match(normalise_scale(cand.text)) if cand is not None else None
                    if m2:
                        v, vm = cand, m2
                        break
                if vm:
                    labelled.append((v, canonical_scale(vm.group(1), exact=v.conf >= 1.0)))
                continue
            m = RE_SCALE_BARE.match(t)
            if m and id(r) in tb_ids:
                bare.append((r, canonical_scale(m.group(1), exact=r.conf >= 1.0)))
        for pool in (labelled, bare):
            words = [rv for rv in pool if not re.search(r"\d", rv[1])]
            if pool and len({v for _, v in pool}) > 1 and len({v for _, v in words}) == 1:
                # "AS NOTED" in the block is the sheet's own statement; the numeric scales beside it belong to views
                pool = words
            if pool and len({v for _, v in pool}) == 1:
                run, val = max(pool, key=lambda rv: (id(rv[0]) in tb_ids, rv[0].bbox[1]))
                self.meta.scale = val
                self._add("titleblock", val, run, run.text, conf=0.85, field="Scale")
                return

    def _widen_titleblock(self, already: bool) -> bool:
        """A scan's raster-found title-block edge (`Sheet.titleblock_x`) can land on an inner divider, leaving the
        sheet number and title left of it. When the narrow region holds no sheet number, take the whole bottom-right
        area instead (right of 55% of the width, inside the bottom band); returns whether it widened."""
        s = self.s
        if already or (s.titleblock_x is None and not self.is_scan):
            return False
        wide = [r for r in s.runs if r.bbox[0] >= 0.55 * s.width and r.bbox[1] >= self.band]
        if len(wide) <= len(self.tb):
            return False
        ids = {id(r) for r in wide}
        self.tb = wide
        self.body = [r for r in s.runs if id(r) not in ids]
        return True

    def parse_titleblock(self, common_large_texts: set[str], _widened: bool = False) -> None:
        """Convention: title block in the bottom strip; sheet number is the large text matching S.x /
        A-101 style; sheet title is the large text nearest to the left/above it; 'Key  Value' pairs on a row.

        The steps, in order: find the sheet number (widening a scan's title-block region and starting again
        when the number is not inside it), guess the title near the number, read a labelled title and the
        'Key  Value' fields, settle which title wins, tidy it, then read revision rows from the bottom band."""
        big = [r for r in self.tb if is_horizontal(r)]
        if (
            not big or ((self.s.titleblock_x is not None or self.is_scan) and len(self.tb) < 6)
        ) and self._widen_titleblock(_widened):
            return self.parse_titleblock(common_large_texts, _widened=True)  # a scan's box edge landed inside the block
        if not big:
            return
        # a doubtful OCR run must not set the bar
        sizes = sorted({r.size for r in big if r.conf >= 0.8} or {r.size for r in big}, reverse=True)
        # 0.75 of the page's single biggest title-block text is fragile when one outlier (a big
        # consultant name/logo, unrelated to the sheet number or title) sets the bar: a real
        # sheet number drawn at a consistent, deliberately large size on every sheet can fall just
        # under 0.75 of a page's company-name text, so the cutoff is 0.7.
        # an OCR box's height varies a few points on identical type, so a scan's "large" bar is lower
        large = [r for r in big if r.size >= sizes[0] * (0.55 if any(r.conf < 1.0 for r in big) else 0.7)]
        sheet_no = self._find_sheet_number(big, _widened)
        if sheet_no is _WIDEN:
            return self.parse_titleblock(common_large_texts, _widened=True)
        if sheet_no is not None:
            self._record_sheet_number(sheet_no)
        title_fact = self._title_near_number(large, big, sheet_no, common_large_texts)
        self._title_label_stack = None
        # A "TITLE" label's block of lines is read first, whole: the nearest line beside the label can be the
        # project name, which is no title, and a wrapped title must keep all its lines ("WEST ANNEX (STAGE 2)"
        # above "STEEL FRAMING PLAN").
        self._title_from_label(sheet_no)
        if "Sheet Title" not in self.meta.fields:
            self._title_from_vertical_label()
        if "Sheet Title" not in self.meta.fields and self.is_scan:
            self._title_from_unlabelled_stack(sheet_no)
        labelled_title_run, labelled_stack = self._read_fields(big, sheet_no)
        if "Sheet Title" not in self.meta.fields:
            self._title_from_label(sheet_no)
        self._prefer_labelled_title(title_fact, labelled_title_run, labelled_stack)
        self._settle_title(title_fact, common_large_texts, sheet_no)
        self._tidy_title()
        self._revision_rows_in_band()

    def _find_sheet_number(self, big: list[TextRun], _widened: bool):
        """The run holding the sheet's own number, None when there is none, or _WIDEN when the title-block region
        must be widened and the parse started again."""
        # Searched across all of `big`, not just `large`: a genuine sheet number's own size is
        # fixed by its template, but a *page*-relative "large" threshold is unreliable when some
        # other run on that particular page (a big view title, a company name) sets an inflated
        # bar (a 14 pt sheet number never clears 0.7 of a 25 pt view title on the same page).
        # RE_SHEET_NO's shape is distinctive enough that picking the biggest match doesn't need a
        # separate size gate first: an incidental small in-body mention of another sheet number
        # will essentially never out-size the real, template-fixed sheet-number field.
        cands = [r for r in big if RE_SHEET_NO.match(r.text.replace(" ", "")) and not is_page_count(r.text)]
        size_vals = self._paper_size_values(big)
        cands = [r for r in cands if r.id not in size_vals]
        labelled = self._labelled_number_runs(big, size_vals)
        big_ids = {id(o) for o in big}
        if (
            labelled
            and not _widened
            and any(id(v) not in big_ids for v in labelled)
            and self._widen_titleblock(_widened)
        ):
            return _WIDEN  # the number sits outside the narrow region: the title block does too
        joined = join_split_numbers(big)
        if _widened:
            # in the widened area, detail marks ("LS3", "R5") also look like short sheet numbers: a short one must be
            # among the biggest texts
            top3 = sorted((r.size for r in big), reverse=True)[:3]
            cands = [r for r in cands if len(r.text.replace(" ", "")) > 4 or r.size >= top3[-1]]
        # Convention (scans only): a numeric drawing number "30417-C" (4-6 digits, dash, one letter) is the
        # sheet number; OCR sometimes drops the letter ("30418-"), and its noise also makes RE_SHEET_NO match
        # junk ("P153"), so on an OCR'd title block the right-most such number replaces those guesses.
        if any(r.conf < 1.0 for r in big):
            dwg = [r for r in big if RE_DRAWING_NO.match(r.text.replace(" ", ""))]
            if dwg:
                cands = [max(dwg, key=lambda r: r.bbox[0])]
        if labelled:
            cands = [max(labelled, key=lambda r: (r.size, r.bbox[0]))]
        if not labelled:
            # Convention: with no labelled field, a long dashed document number ("PX1-12-STR-04-0062-009") at least
            # as big as a short candidate is the sheet number; the short one ("DR4", a grid bubble in the title
            # block's strip) is not.
            longs = [
                r
                for r in big
                if r.id not in size_vals
                and r.conf >= 0.6
                and 11 <= len(document_number_text(r)) <= 32
                and RE_DOC_NO.match(document_number_text(r))
                and sum(c in "-." for c in document_number_text(r)) >= 2
            ]
            if longs and all(
                len(c.text.replace(" ", "")) <= 6 and c.size <= 1.25 * max(r.size for r in longs) for c in cands
            ):
                cands = [max(longs, key=lambda r: (r.size, r.bbox[1]))]
        if not cands:
            docs = [
                r
                for r in big + joined
                if r.conf >= 0.6
                and 8 <= len(document_number_text(r)) <= 32
                and RE_DOC_NO.match(document_number_text(r))
            ]
            if docs:
                cands = [max(docs, key=lambda r: (r.size, r.bbox[0]))]
        if not cands and self._widen_titleblock(_widened):
            return _WIDEN
        if not cands:
            return None
        return max(cands, key=lambda r: (r.size, r.bbox[0]))

    def _paper_size_values(self, big: list[TextRun]) -> set[str]:
        """Ids of the values beside a "SHEET SIZE" / "PAPER SIZE" label ("A1", "D", "ARCH E1"): a paper size, never a
        sheet number."""
        size_vals = set()
        for lab in big:
            if re.sub(r"[^A-Z]", "", lab.text.upper()) in ("SHEETSIZE", "PAPERSIZE", "SIZE", "DWGSIZE", "DRAWINGSIZE"):
                v = self._right_of(lab, big, max_gap=120) or self._below_label(lab, big)
                if v is not None:
                    size_vals.add(v.id)
        return size_vals

    def _labelled_number_runs(self, big: list[TextRun], size_vals: set[str]) -> list[TextRun]:
        """Numbers held by a field labelled "DRAWING #" / "DWG NO" / "SHEET NO", right of the label or under it, or a
        big boxed number over a small "SH.NO." caption.

        A consultant's or a client's drawing number carries another word in front of the label and is not this one.
        The label may sit outside `self.tb` (a right-hand strip whose divider was misjudged), so the whole bottom band
        is searched, and a scan misspells it ("DRABING NO"): a close spelling counts."""
        pool = big + [
            r for r in self.s.runs if r.bbox[1] >= self.band and is_horizontal(r) and id(r) not in {id(o) for o in big}
        ]
        labelled = []
        # a long number a scan cut in two ("PX1-" + "12-STR-00-0140-003") reads whole
        joined_pool = join_split_numbers(pool)
        for lab in pool:
            # a bilingual caption ("DWG. NO. | NO. DESSIN") reads by its first language
            norm_lab = re.sub(r"[^A-Z#]", "", lab.text.split("|")[0].upper())
            m_lab = re.search(
                r"(DRAWING#|DRAWINGNO|DRAWINGNUMBER|DWG#|DWGNO|DWGNUMBER|SHEET#|SHEETNO|SHEETNUMBER)$", norm_lab
            ) or fuzzy_number_label(norm_lab)
            if m_lab and not re.search(r"CONSULTANT|CLIENT|REF|PARENT|OTHER|SEE|PACKAGE", norm_lab[: m_lab.start()]):
                near = [
                    o
                    for o in pool + joined_pool
                    if o is not lab
                    and o.id not in size_vals
                    and (o.bbox[0] >= lab.bbox[0] - 10 or x_overlap(lab.bbox, o.bbox) > 0)
                    and o.bbox[0] - lab.bbox[2] <= 150
                    and -0.5 * lab.size <= o.bbox[1] - lab.bbox[1]
                    and o.bbox[1] - lab.bbox[3] <= 2.5 * lab.size
                ]
                ok = []
                # nearest first: beside the label, then under it; a joined number ahead of its halves
                for v in sorted(
                    near,
                    key=lambda o: (
                        (o.bbox[1] - lab.bbox[1])
                        + 0.3 * abs(o.bbox[0] - lab.bbox[0])
                        - (6.0 if "+" in str(o.id) else 0.0)
                    ),
                ):
                    txt = v.text.replace(" ", "")
                    # two real words are a description, not a number
                    if (
                        RE_SHEET_NO.match(txt)
                        or RE_DRAWING_NO.match(txt)
                        or (RE_DOC_NO.match(document_number_text(v)) and 8 <= len(document_number_text(v)) <= 32)
                        or (
                            labelled_number_ok(txt)
                            and sum(1 for w in v.text.split() if w.isalpha() and len(w) >= 3) < 2
                        )
                    ):
                        ok.append(v)
                if ok:  # a series number ("S-1420-08") beats its own bare digits ("1420") printed beside it
                    labelled.append(
                        next((v for v in ok if RE_SHEET_NO.match(v.text.replace(" ", ""))), ok[0])
                        if ok[0].text.strip().isdigit()
                        else ok[0]
                    )
        if not labelled:
            # a boxed number: the number is big, the small caption ("SH.NO.", "SHEET NO.") sits under it
            for lab in pool:
                if re.sub(r"[^A-Z#]", "", lab.text.upper()) in (
                    "SHNO",
                    "SHTNO",
                    "SH#",
                    "SHT#",
                    "SHEETNO",
                    "SHEET#",
                    "DWGNO",
                    "DRAWINGNO",
                    "DWG#",
                ):
                    above = [
                        o
                        for o in self.s.runs
                        if is_horizontal(o)
                        and o is not lab
                        and o.size >= 1.4 * lab.size
                        and 0 <= lab.bbox[1] - o.bbox[3] <= 3 * lab.size
                        and x_overlap(lab.bbox, o.bbox) > 0
                        and not is_page_count(o.text)
                        and o.id not in size_vals
                        and (RE_SHEET_NO.match(o.text.replace(" ", "")) or RE_DRAWING_NO.match(o.text.replace(" ", "")))
                    ]
                    if above:
                        labelled.append(max(above, key=lambda o: o.size))
                        break
        return labelled

    def _record_sheet_number(self, sheet_no: TextRun) -> None:
        """Set the sheet number from its run, repairing a scan's misreads, and add the sheet fact."""
        self.meta.number = (
            (
                sheet_no.text.replace(" ", "").upper().rstrip("-")
                if sheet_no.conf < 1.0
                else sheet_no.text.replace(" ", "")
            )
            if RE_SHEET_NO.match(sheet_no.text.replace(" ", "")) or RE_DRAWING_NO.match(sheet_no.text.replace(" ", ""))
            else document_number_text(sheet_no).upper()
        )
        self.meta.number = re.sub(r"-{2,}", "-", self.meta.number)  # a scan reads a long dash as two
        # "AB6O2-S-3O18-1": a letter O among the digits of a segmented document number
        if self.meta.number.count("-") >= 2:
            self.meta.number = "-".join(
                re.sub(r"(?<=\d)O|O(?=\d)", "0", seg)
                if re.fullmatch(r"[A-Z]{0,3}[0-9O]+", seg) and re.search(r"\d", seg)
                else seg
                for seg in self.meta.number.split("-")
            )
        # "12-3B-M-41SHT10F3": the sheet-of-set line glued on
        self.meta.number = re.sub(r"(?<=\w)SH(?:T|EETS?)\.?\d(?:[O0]F|/)\d+$", "", self.meta.number)
        self._add("sheet", self.meta.number, sheet_no, sheet_no.text, conf=0.95, role="sheet_number")

    def _title_near_number(self, large, big, sheet_no, common_large_texts: set[str]):
        """The title guessed from position: the large text nearest the sheet number, with the lines it wraps onto.
        Sets meta.title and title_src; returns the sheet_title fact it added, or None."""
        # >= 3 letters: a bare dimension in the bottom band ("375", "97") or a single stray letter ("F", "L")
        # is never a sheet title -- a blank title is better than a wrong one.
        # nor a field label a scan misspelt ("DRAWNG N0.")
        titles = [
            r
            for r in large
            if r is not sheet_no
            and r.text not in common_large_texts
            and not RE_SHEET_NO.match(r.text.replace(" ", ""))
            and not _is_titleblock_label(r)
            and not RE_FIELD_ROW.match(r.text.strip())
            and sum(c.isalpha() for c in r.text) >= 3
            and not RE_REV_CODE.match(r.text.strip())
            and r.conf >= 0.8  # OCR doubts (logo fragments) are not titles
            and not (self.is_scan and not re.search(r"\d", r.text) and fuzzy_label_line(r.text))
        ]
        title_fact = None
        if titles and sheet_no:
            title = min(
                titles,
                key=lambda r: abs(r.center[0] - sheet_no.center[0]) + 0.3 * abs(r.center[1] - sheet_no.center[1]),
            )
            # A title wrapped over several lines is several runs: join same-size runs stacked directly above/below it
            # (gap under 1.3 line heights, overlapping x-range), top to bottom, so "GROUND FLOOR AND ROOF FRAMING
            # PLANS" is not cut to its nearest line ("ROOF FRAMING PLANS").
            chain = [title]
            grew = True
            while grew and len(chain) < 5:
                grew = False
                for o in titles:
                    if (
                        o in chain
                        or abs(o.size - title.size) > (0.25 if self.is_scan else 0.05) * title.size
                        or not is_horizontal(o)
                    ):
                        continue
                    if any(o.text.strip() == c.text.strip() for c in chain):
                        continue  # the same line printed again (a title repeated in the title strip), not a wrap
                    top, bot = min(chain, key=lambda r: r.bbox[1]), max(chain, key=lambda r: r.bbox[3])
                    # a scan's boxes are padded: lines of one block overlap a little
                    lo = -0.8 * title.size if self.is_scan else 0
                    below = lo <= o.bbox[1] - bot.bbox[3] <= 0.6 * title.size and x_overlap(bot.bbox, o.bbox) > 0
                    above = lo <= top.bbox[1] - o.bbox[3] <= 0.6 * title.size and x_overlap(top.bbox, o.bbox) > 0
                    if below or above:
                        chain.append(o)
                        grew = True
                        break
            if title.conf < 1.0:
                # a scan reads one printed line as several runs ("GALLERY FRAMING -" + "SHEET 1"): join same-size runs
                # on the same row, left to right, when the gap is under one text height
                grew = True
                while grew and len(chain) < 5:
                    grew = False
                    for o in titles:
                        if (
                            o in chain
                            or abs(o.size - title.size) > 0.15 * title.size
                            or not same_row(title, o, 0.4 * title.size)
                        ):
                            continue
                        left, right = min(chain, key=lambda r: r.bbox[0]), max(chain, key=lambda r: r.bbox[2])
                        if (
                            -0.5 * title.size <= o.bbox[0] - right.bbox[2] <= title.size
                            or -0.5 * title.size <= left.bbox[0] - o.bbox[2] <= title.size
                        ):
                            chain.append(o)
                            grew = True
                            break
            chain.sort(key=lambda r: (round(r.bbox[1] / (0.6 * title.size)), r.bbox[0]))
            full_title = " ".join(r.text.strip() for r in chain)
            if title.conf < 1.0 and re.search(r"\bSHEET$", full_title):
                # a scan reads "GALLERY - SHEET" and its small sheet-of-set digit as two runs: re-attach the digit
                digit = [
                    o
                    for o in big
                    if o is not title
                    and re.fullmatch(r"\d{1,2}", o.text.strip())
                    and same_row(title, o, 0.6 * title.size)
                    and -0.5 * title.size <= o.bbox[0] - title.bbox[2] <= 1.5 * title.size
                ]
                if digit:
                    full_title += " " + digit[0].text.strip()
                    self.used.add(digit[0].id)
            self.meta.title = full_title
            self.title_src = "near_number"
            title_fact = self._add("titleblock", full_title, title, full_title, conf=0.85, field="sheet_title")
            if len(chain) > 1:
                title_fact.bbox = (
                    min(r.bbox[0] for r in chain),
                    min(r.bbox[1] for r in chain),
                    max(r.bbox[2] for r in chain),
                    max(r.bbox[3] for r in chain),
                )
                self.used.update(r.id for r in chain)
        elif titles:
            self.meta.title = titles[0].text
            self.title_src = "first"
        return title_fact

    def _read_fields(self, big, sheet_no):
        """The 'Key  Value' fields of the title block (TITLEBLOCK_KEYS), into meta.fields and titleblock facts.
        Returns (the run of a labelled sheet title, the lines of its block), each None when there is none."""
        labelled_title_run = labelled_stack = None
        # key / value pairs
        for r in big:
            m_lv = RE_PROJNO_INLINE.match(r.text.strip())
            if m_lv and plausible_project_no(re.split(r"[,;]", m_lv.group(2))[0].strip()):
                # label and number written as one run ("PROJECT NUMBER: ABC123456/2031-014", "Job Number: 31205, Project
                # Contact: ...")
                fkey = "JOB NUMBER" if m_lv.group(1).upper().startswith("JOB") else "PROJECT NUMBER"
                val = re.split(r"[,;]", m_lv.group(2))[0].strip()
                self.meta.fields[fkey.title()] = val
                self._add("titleblock", val, r, r.text, conf=0.85, field=fkey.title())
                continue
            key = r.text.rstrip(":.# ").upper()
            key = TITLEBLOCK_KEY_ALIASES.get(key, key)
            if key == "SHEET TITLE" and "Sheet Title" in self.meta.fields:
                continue  # already read as a block under its label
            if key in TITLEBLOCK_KEYS:
                # A bare key run (e.g. "DATE") sitting in the same row as a revision-table column
                # header ("DESCRIPTION", "ISSUE"/"ISSUED FOR") is itself that table's own header
                # cell, not a title-block label -- seen where the real "DATE:" label sits
                # elsewhere on the sheet. Skip it entirely rather than trying to value-pair it, since
                # both `_right_of` and `_below_label` land on more of that same header row/table.
                if any(o.text.strip().upper() in REV_TABLE_HEADER_WORDS for o in big if o is not r and same_row(r, o)):
                    continue
                # On a template with several label/value columns in one row ("PROJECT NO." then
                # "DRAWING NO." to its right, each with its own value below rather than beside it),
                # _right_of can land on the *next column's label*, not a value. Fall
                # through to _below_label instead of accepting that, rather than only rejecting it
                # after the fact and giving up on the field entirely.
                v = None
                for cand in (self._right_of(r, big), self._below_label(r, big)):
                    if cand is None or cand.text.rstrip(":.# ").upper() in NON_VALUE_WORDS:
                        continue
                    ct = cand.text.strip()
                    if key == "SHEET TITLE" and not plausible_title(ct, frozenset(), one_word_ok=True):
                        # a TITLE label's neighbour that reads as no title ("O.A.A", an initials box) is not its value
                        continue
                    if key == "SCALE" and not RE_SCALE_BARE.match(normalise_scale(ct)):
                        # a SCALE label's neighbour that is not a scale ("DWG. SIZE", the next label) is not its value
                        continue
                    if not re.search(r"[A-Za-z0-9]", ct) or ct.upper().rstrip(":.") in PLACEHOLDER_VALUES:
                        continue  # punctuation-only / unfilled-template placeholder, not a value
                    if key in ("PROJECT NUMBER", "PROJECT NO", "JOB NO", "JOB NUMBER") and not plausible_project_no(ct):
                        # a job number is digits (maybe a short prefix): "LSD", "EAST WING (PHASE 1)" or a neighbouring
                        # label is not one
                        continue
                    if key not in SHEET_ID_KEYS and (cand is sheet_no or (self.meta.number and ct == self.meta.number)):
                        continue  # the sheet number is never another field's value ("Checked By: S.2")
                    v = cand
                    break
                if v is not None:
                    self.meta.fields[key.title()] = v.text
                    self._add("titleblock", v.text, v, f"{r.text} {v.text}", conf=0.9, field=key.title())
                    if key == "SCALE":
                        self.meta.scale = canonical_scale(
                            RE_SCALE_BARE.match(normalise_scale(v.text)).group(1), exact=v.conf >= 1.0
                        )
                    if key == "SHEET TITLE":
                        labelled_title_run = v
                        stack = self._title_stack(v, big, sheet_no)
                        if len(stack) > 1:
                            keep = self._drop_repeated_head(stack)  # project / client lines repeat on every sheet
                            keep = [o for o in keep if not RE_OCR_JUNK.search(o.text)] or keep[-1:]
                            self.meta.fields["Sheet Title"] = " ".join(o.text.strip() for o in keep)
                            self.used.update(o.id for o in stack)
                            labelled_stack = keep
        return labelled_title_run, labelled_stack

    def _prefer_labelled_title(self, title_fact, labelled_title_run, labelled_stack) -> None:
        """When a title was read under its label, it replaces the position guess, and the sheet_title fact is
        pointed at the labelled text."""
        # An explicit "Sheet Title" label/value pair (just extracted above, if present) is a direct,
        # unambiguous signal -- prefer it over the proximity-based guess above, which is only a
        # fallback for templates that don't label the title explicitly.
        if "Sheet Title" in self.meta.fields:
            self.meta.title = self.meta.fields["Sheet Title"]
            self.title_src = "label"
            # The proximity guess above may have grabbed something else entirely (the project
            # number, a view title) and left a stray `sheet_title` fact behind -- point that fact at the
            # labelled title instead (or add it if there was no guess), so rules citing `sheet_title`
            # facts cite the real title.
            if labelled_title_run is None and self._title_label_stack:
                labelled_title_run = self._title_label_stack[0]
                labelled_stack = self._title_label_stack
            if labelled_title_run is not None:
                t_text, t_box = labelled_title_run.text, tuple(labelled_title_run.bbox)
                if labelled_stack:
                    t_text = self.meta.fields["Sheet Title"]
                    t_box = (
                        min(o.bbox[0] for o in labelled_stack),
                        min(o.bbox[1] for o in labelled_stack),
                        max(o.bbox[2] for o in labelled_stack),
                        max(o.bbox[3] for o in labelled_stack),
                    )
                if title_fact is not None:
                    title_fact.value = t_text
                    title_fact.source_text = t_text
                    title_fact.bbox = t_box
                else:
                    self._add("titleblock", t_text, t_box, t_text, conf=0.9, field="sheet_title")

    def _settle_title(self, title_fact, common_large_texts: set[str], sheet_no) -> None:
        """Drop a position guess that cannot be a title, then fall back to finding the title by vocabulary."""
        if (
            self.meta.title
            and self.title_src in ("near_number", "first")
            and not plausible_title(self.meta.title, self.repeated, one_word_ok=self.title_src == "near_number")
        ):
            # the large-text guess picked a logo, a company line or a note: drop it and look by vocabulary instead
            if title_fact is not None and title_fact in self.facts:
                self.facts.remove(title_fact)
            self.meta.title, self.title_src = "", ""
        if not self.meta.title:
            self._title_fallback(common_large_texts, sheet_no)
            if not self.meta.title:
                self._title_fallback(common_large_texts, sheet_no, extra=True)
        elif self.is_scan and self.title_src == "near_number" and " " not in self.meta.title and title_fact is not None:
            # a scan's one-word "title" beside the number is often a stamp or a seal ("CERTIFIED"): a stacked block that
            # names a drawing type wins
            held, held_fact = self.meta.title, title_fact
            self.meta.title, self.title_src = "", ""
            self._title_fallback(common_large_texts, sheet_no, foot_only=True)
            if self.meta.title:
                if held_fact in self.facts:
                    self.facts.remove(held_fact)
            else:
                self.meta.title, self.title_src = held, "near_number"

    def _set_title(self, title: str) -> None:
        """Replace the sheet title, and the value of the sheet_title facts that hold the old one."""
        if title == self.meta.title:
            return
        for f in self.facts:
            if f.kind == "titleblock" and f.attrs.get("field") == "sheet_title" and f.value == self.meta.title:
                f.value = f.source_text = title
        self.meta.title = title

    def _tidy_title(self) -> None:
        """Repairs to the chosen title: a scan's doubled parenthesis and misread digits, glued words, a trailing
        dash, a sheet-of-set suffix and field labels a line join left on its end."""
        if self.meta.title and self.is_scan:
            undoubled = re.sub(r"(\([^()]{3,12}\))\s+\1", r"\1", self.meta.title)  # "(SHT 2/5)" read twice
            self._set_title(fix_title_digits(undoubled))
        if self.meta.title:
            # a scan loses the space between two title words ("TYPICALDETAILS"), and a title run into its dash
            # ("GENERAL NOTES -") ends at its last word
            self._set_title(split_glued_title(re.sub(r",(?=[A-Za-z])", ", ", self.meta.title)).rstrip(" -\u2013"))
        if self.meta.title and RE_SHEET_OF.search(self.meta.title):
            self._set_title(RE_SHEET_OF.sub("", self.meta.title).strip())
        if self.meta.title:
            self._set_title(trim_stray_labels(self.meta.title))

    def _revision_rows_in_band(self) -> None:
        """Revision rows read from the whole bottom band (`self.band`), not just `self.tb`: under the right-strip
        convention (`titleblock_runs`) a revision log drawn left of the divider still sits in the bottom band
        even though it is drawing-area `body` text, and a numbered row that low on the sheet with a date is a
        revision, not body content."""
        # a row is: small number | description | date
        if self._rev_table_found:
            return
        band_runs = [r for r in self.s.runs if r.bbox[1] >= self.band and is_horizontal(r)]
        for r in band_runs:
            m = RE_ITEM_NO.match(r.text)
            if not m or r.size > 10:
                continue
            row = [o for o in band_runs if o is not r and same_row(r, o, tol=3.5) and o.bbox[0] > r.bbox[2]]
            row.sort(key=lambda o: o.bbox[0])
            # A plot/print timestamp ("2031-05-14 9:42:00 AM", a page footer stamped at export time,
            # not a drafted revision date) also matches RE_DATE's bare `\d{4}-\d{2}-\d{2}` -- the
            # attached clock time is what tells the two apart.
            dates = [o for o in row if RE_DATE.search(o.text) and not re.search(r"\d{1,2}:\d{2}", o.text)]
            desc = [o for o in row if o not in dates and not RE_ITEM_NO.match(o.text)]
            # A date is required: a numbered note ("3. ALL BOLTS ...") in the same bottom band looks like a
            # revision row otherwise. A revision row states when it happened; a note does not.
            if desc and dates and desc[0].bbox[0] - r.bbox[2] < 200 and not reads_like_a_note(desc[0].text):
                # `row` is x-sorted; the *first* date is the one immediately after the revision
                # number -- a second date further right in the same wide row is usually a different
                # field's value swept in by the row-continuation tolerance, not a second revision
                # date (e.g. rev rows that also catch a "date drawn" field further along the row).
                d = dates[0].text
                bbox = (
                    r.bbox[0],
                    min(o.bbox[1] for o in [r] + row),
                    max(o.bbox[2] for o in [r] + row),
                    max(o.bbox[3] for o in [r] + row),
                )
                self._add(
                    "revision",
                    f"Rev {m.group(1)}: {desc[0].text}" + (f" ({d})" if d else ""),
                    bbox,
                    " ".join(o.text for o in [r] + row),
                    conf=0.8,
                    number=m.group(1),
                    description=desc[0].text,
                    date=d,
                )
                for o in [r] + row:
                    self.used.add(o.id)
