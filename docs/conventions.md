# Drafting conventions the rules assume

The parsers do not understand a drawing; they recognise how structural drawings are usually drafted.
This page lists, per rule group, what the rules expect to find. A sheet drafted another way is not
an error: the rule simply does not fire, and the text is still kept as searchable text.

The conventions are those of North American steel and concrete drawing sets, metric or imperial.
They are written in the code as `Convention:` docstrings next to the rule that relies on them; this
page collects them.

## Sheets and the title block (`parse/sheet/titleblock.py`, `titles.py`, `parse/layout.py`)

- **Where the title block is.** Either a strip along the bottom of the sheet (most sets) or a strip
  down the right-hand edge, recognised by a long vertical divider between 75% and 96% of the sheet
  width with text to its right. Lines drawn over one another (a column on its grid line) count once,
  so they cannot pass for a divider.
- **Sheet number.** The large text in the title block shaped like a sheet id: `S-201`, `S2.01`,
  `S.3`, `A-101`. When none is found the sheet is called `P<page>`.
- **Sheet title.** The large text nearest the sheet number, left of or above it. Fallbacks, in
  order: a `TITLE` / `DRAWING TITLE` label with its value beside or under it; stacked capital lines
  naming a drawing type (`PLAN`, `ELEVATIONS`, `DETAILS`, `SCHEDULE` ...); a title written up the
  side of the sheet. Lines printed on most sheets of the set are the project and client, not titles.
- **Fields.** `Key  Value` pairs on one row, or a label with its value below it in the same cell:
  `PROJECT NO.`, `DATE`, `DRAWN BY`, `CHECKED BY`, `SCALE` and the like.
- **Scale.** `1:50`, `1 : 100`, `3/4" = 1'-0"`, `N.T.S.`, `AS NOTED`; foot and inch marks are
  normalised first. Several different scales on one sheet mean per-view scales: the sheet scale is
  left empty and each view keeps its own.
- **Project location.** A labelled `LOCATION`, a street address, a `City, Region` line (any
  Canadian province or territory, any US state, by name or code), or a legal land description. A
  two-letter region code counts only where it cannot be an ordinary word (end of line, or followed
  by a postal code).

## Revisions (`parse/sheet/revisions.py`)

Three readers, tried in turn until one finds rows:

1. A table with a header row (`REV` beside `DESCRIPTION` or `ISSUED FOR`, optionally `DATE`),
   wherever it is on the sheet, rows below the header.
2. A table whose header is at its foot (newest row on top), whose number column is headed `No.`,
   or whose rows wrap over several lines. Rows are bands opened by each entry of the number column.
3. Rows that start with a dotted revision code (`0.A.0`) followed by a description and a date, with
   or without a header.

A revision has a code, a description naming an issue purpose and a date in a recognised shape. A
title-block field label (`DRAWN BY`) is never a revision cell.

## Member labels (`parse/sheet/members.py`, `parse/members.py`)

- **Designations.** Standard section names: `W310X39`, `HSS152X152X9.5`, `L102X102X9.5`, `C310X31`,
  `PL25X350X350`, `ROD20`, pipe and joist designations, and imperial sizes with fractions
  (`L3-1/2X3X3/8`). Spellings are normalised so that equal sizes compare equal.
- **Orientation gives the role.** A label is written along its member, so its rotation says how the
  member runs: horizontal labels are beams, vertical labels columns, diagonal labels braces. This is
  the main source of wrong answers (see [evaluation.md](evaluation.md)): a beam drawn up the sheet in
  a plan has a vertical label.
- **Plates.** `PL t` is a thickness; `PL AxBxC` is a plate size and its thickness is the smallest of
  the three numbers, whatever the order.
- **Angles.** A text run that is only a degree value (`31.0°`) is an angle annotation; it is kept
  with its own orientation, and the angle question reports it with the view it sits in.

## Grids, callouts, levels and views (`parse/sheet/symbols.py`)

- **Grid bubble.** A full circle 25 to 50 pt across with a 1 to 3 character label centred in it.
- **Detail callout.** A split circle: a detail number over a sheet id (`2` over `S-301`). A callout
  whose sheet id is the sheet's own number, placed just left of a view title, is that view's number,
  not a cross-reference.
- **Level marker.** A name (`T.O. STEEL`) with a level value directly below it, next to a small
  datum target.
- **View title.** `<n>  TITLE` with a scale directly below. Every fact is assigned to the nearest
  view title below it, since titles sit under their drawing.
- **References in text.** `SEE DETAIL 1/S-301`, `SEE DWG S-501`: each becomes a reference fact,
  and the set-level pass marks references to sheets that are not in the set.

## Dimensions (`parse/sheet/dimensions.py`, `parse/dimension_values.py`)

- **What a dimension is.** A bare number written parallel to a thin line running under or along it,
  or set in a gap of its own line. A number inside a sentence is not a dimension.
- **Units.** Millimetres unless the sheet says otherwise; feet and inches are read from `12'-6"`
  forms; a number may carry its own unit; `R` and `Ø` mark radius and diameter.
- **Tables are not dimensions.** A block of rows, each of three or more cells on one baseline at a
  steady pitch with columns lined up, is a table: its numbers are cells.
- **Chains.** Dimensions on one line that add up to a dimension on a parallel line (within 0.3%)
  are a chain and its total; both are marked.
- **Measured scale.** A dimension's value divided by the length of its line on paper is a measured
  scale. The largest cluster of agreeing values in a view is checked against the titled scale, which
  catches a wrong scale note or a print that was reduced.

## Notes, materials and loads (`parse/sheet/notes.py`, `parse/note_text.py`, `parse/materials.py`)

- **Note blocks.** A heading in capitals ending with `:` (`GENERAL NOTES:`, `MATERIALS:`), then
  items numbered `1.` or bulleted, wrapping within their column. One paragraph that holds several
  numbered items is split where item n is followed by item n+1.
- **Material clauses.** A note citing a standard (`CSA G40.21`, `ASTM A325M`, `ASTM F1554`)
  becomes a material fact per distinct standard, with the component it applies to and a yield
  strength when one is given (`Fy=350 MPa`); a clause stating several yields keeps them all.
- **Design criteria.** `NAME = value` parameters, and load tables where the label (`LIVE LOAD`) and
  the value (`4.8 kPa`) are separate pieces of text, the value to the right of or below the label.
- **Weld symbols.** A thin horizontal reference line carrying a right-triangle fillet glyph; the
  size is the number just left of the triangle. A triangle below the line is the arrow side, above
  it the other side, both together both sides. A `TYP.` on the same row is kept.
- Everything else becomes a **text** fact at low confidence, so a keyword search can still find it.

## Scans (`drawing_reader.ocr`, `parse/scan_repair.py`)

Everything above applies to text read by OCR, with these differences:

- OCR text is approximate (`O`/`0`, `S`/`5`, missing spaces). Facts from OCR are capped below
  vector confidence, and every answer from a scanned set carries a caveat.
- Circles are not recovered from a raster, so grid bubbles and level-marker targets are not found.
- Note headings without a colon are accepted on scans when they are short capital lines alone on
  their row that end in a heading word (`GENERAL NOTES`, `MATERIALS`).
- Set-level repairs: a set numbers its sheets in one scheme, so a sheet number read partly or with
  a digit for a letter is completed from its siblings. A member size seen once that differs by one
  character from a size seen many times is flagged as a likely misread, never changed.
