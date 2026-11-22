"""Text extraction from vector pages: symbol-font text and tracked-out lettering are turned back
into ordinary words before any rule reads them."""

from __future__ import annotations

from drawing_reader.ingest.vector import _despace_line, _is_letter_spaced, decode_symbol_font


def symbol_font(text):
    """`text` as a symbol-encoded font stores it: each character moved into the private-use area."""
    return "".join(chr(ord(c) + 0xF000) for c in text)


def tracked_line(word_lengths, pitch=12.0, word_gap=6.0, size=14.0, letter_width=5.0):
    """A line as the PDF library reports wide letter tracking: one box per letter, a space box after
    each, and a slightly bigger gap between words."""
    chars, x = [], 80.0
    for length in word_lengths:
        for _ in range(length):
            chars.append({"c": "N", "bbox": (x, 0, x + letter_width, size)})
            chars.append({"c": " ", "bbox": (x + letter_width, 0, x + pitch, size)})
            x += pitch
        x += word_gap
    return {"spans": [{"size": size, "chars": chars}]}


def test_a_line_set_in_a_symbol_font_is_decoded_to_plain_text():
    """A word-processor or CAD export can store a line as private-use characters, one per letter."""
    assert decode_symbol_font(symbol_font("TYPICAL: 2")) == "TYPICAL: 2"


def test_a_stray_symbol_in_real_text_is_left_as_read():
    """One symbol character (a bullet) in an ordinary line does not make the line symbol text."""
    bullet = symbol_font("·")
    assert decode_symbol_font(f"{bullet} weld all round") == f"{bullet} weld all round"
    assert decode_symbol_font("BASE PLATE DETAILS") == "BASE PLATE DETAILS"


def test_tracked_out_lettering_is_recognised_by_its_single_letter_tokens():
    assert _is_letter_spaced("F R A M I N G P L A N")
    assert not _is_letter_spaced("SECTION B-B")


def test_tracked_out_lettering_is_rejoined_with_word_breaks_at_the_wider_gaps():
    """A space sits between every pair of letters, so a word break is only a wider gap."""
    assert _despace_line(tracked_line([6, 4, 5])) == "NNNNNN NNNN NNNNN"


def test_marks_far_apart_in_one_line_are_not_tracked_lettering():
    """Grid bubbles in a row come as one "line" of single letters: they are not a word."""
    assert _despace_line(tracked_line([4], pitch=350.0)) == ""
