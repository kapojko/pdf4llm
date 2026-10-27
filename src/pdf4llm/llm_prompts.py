"""All prompt templates (whole-chunk / line / cell).

Prompts are iterated on most often; they live apart from logic on
purpose. Classification (llm_classify) only ever picks between the
TECHNICAL_* and GENERAL_* variants of the same template.
"""
from __future__ import annotations




# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_COMMON_RULES = """You fix whitespace defects in extracted PDF-to-Markdown text.
ALLOWED ONLY:
(a) remove stray spaces inside and between words so falsely split words join
    correctly (deleting false line breaks so split words join is included);
(b) collapse runs of spaces;
(c) delete a false line break inside a paragraph, replacing it with one space
    (or with nothing where two word halves join);
(d) remove a '<br>' marker (or replace it with one space) where PDF
    extraction left it inside one word ('Co<br>ntrol' -> 'Control').
FORBIDDEN:
- adding, deleting, reordering or changing ANY other non-whitespace character;
- removing or altering horizontal rule lines ('---' on its own line) — keep
  them byte-identical;
- changing the spacing around em/en dashes ('—', '–') — keep it as-is;
- translating, rephrasing, summarising, "improving" grammar or spelling;
- changing the number of lines that start with '|' (table rows) or the number
  of '|' characters in them;
- altering any digit, number, hex token (0x1A2B), unit or value;
- adding comments, notes, headings, code fences or explanations.
Return ONLY the corrected Markdown, nothing else."""

TECHNICAL_SYSTEM_PROMPT = (
    "The text comes from an electronic component datasheet or microcontroller "
    "reference manual. PDF extraction left false spaces inside words.\n"
    "Typical fixes in this domain: 'D-t yp e' -> 'D-type', 'fli p -flo p' -> "
    "'flip-flop', 'Orderin g' -> 'Ordering'. Spaced subscript terms join to "
    "the document's own spelling ('V CC' -> 'VCC'). Underscores ('_') are "
    "part of real register and signal names ('SDRAMC_WPSR', 'R8_USB_CTRL') "
    "— never add, delete, or move them.\n"
    "Register values, pin numbers, voltages, timings and part numbers are "
    "sacrosanct: never let two numbers or a number and a symbol merge "
    "('2 0' must NOT become '20', '0.5 V' must stay '0.5 V').\n"
    + _COMMON_RULES
)

GENERAL_SYSTEM_PROMPT = (
    "The text is general document prose converted from PDF. PDF extraction "
    "left false spaces inside words and false line breaks.\n"
    "Typical fixes: 'examp le' -> 'example', 'wo rd' -> 'word'.\n"
    + _COMMON_RULES
)

# ---------------------------------------------------------------------------
# Unit-level protocol prompts (line / cell echo requests)
#
# The echo format is the discipline: measured on ling-3.0-tiny, per-line and
# per-cell requests produced ZERO content violations (vs ~70% rejections for
# whole-table chunks), because a short numbered unit leaves no room for the
# model's editorial instincts. Sampling is never overridden for these
# requests — the server-side defaults apply unless llm_sampling is set.
# ---------------------------------------------------------------------------

_LINE_RULES = """You fix whitespace defects in text extracted from a PDF.
Input: numbered lines 'N| text'.
Fix ONLY false spaces inside words ('examp le' -> 'example', 'D-t yp e' ->
'D-type', 'fli p -flo p' -> 'flip-flop').
HARD RULES:
- return EXACTLY the same numbered lines: same indices, same order, one line
  of output per line of input, no extra text, no code fences;
- never add, delete or reorder words; never change any letter, digit,
  number, hex token (0x1A2B), unit or value; never merge or split numbers
  ('2 0' must stay '2 0');
- never DELETE punctuation. Dash-like characters may be rewritten as '-'
  but never removed; bullet glyphs may be rewritten as '*';
- a '<br>' marker is a false line-break artifact: remove it when it splits
  one word ('Co<br>ntrol' -> 'Control'), otherwise keep it as-is;
- if a line has no defects, return it unchanged.

Some lines may be followed by a 'NOTE k: ...' line that describes a mistake
in a previous rejected answer for line k. NOTE lines are not text: never
repeat or echo them, just apply the warning to line k.

Example
input:
1| D-t yp e
2| Standard operating voltage
output:
1| D-type
2| Standard operating voltage
(the second line has no defects and is copied unchanged)
"""

TECHNICAL_LINE_PROMPT = (
    "The lines come from an electronic component datasheet or microcontroller "
    "reference manual. Underscores ('_') are part of real register and signal "
    "names ('SDRAMC_WPSR', 'R8_USB_CTRL') — never add, delete, or move them.\n"
    + _LINE_RULES
)
GENERAL_LINE_PROMPT = _LINE_RULES

_CELL_RULES = """You fix false spaces in words inside table cells extracted from a PDF.
Input: numbered cells 'N| text', then the original table row as CONTEXT.
Fix ONLY false spaces inside words ('R es .' -> 'Res.', 'D-t yp e' ->
'D-type'); collapse double spaces inside a cell.
HARD RULES:
- return EXACTLY the numbered cell lines: same indices, same order, one line
  per cell, no extra text, no code fences; never return the context row;
- never change any letter, digit, number, hex token, unit or value; never
  merge or split numbers ('2 0' must stay '2 0');
- never add or remove cell boundaries ('|');
- a '<br>' marker is a false line-break artifact: remove it when it splits
  one word ('Co<br>ntrol' -> 'Control'), otherwise keep it as-is;
- if a cell has no defects, return it unchanged.

A cell may be followed by a 'NOTE k: ...' line that describes a mistake in a
previous rejected answer for cell k. NOTE lines are not text: never repeat
or echo them, just apply the warning to cell k.

Example
input:
1| D-t yp e
2| Standard operating voltage
CONTEXT:
row: | D-t yp e | Standard operating voltage | 2 . 5 V |
output:
1| D-type
2| Standard operating voltage
(the second cell has no defects and is copied unchanged; the CONTEXT row is
never echoed)
"""

TECHNICAL_CELL_PROMPT = (
    "The cells come from an electronic component datasheet or microcontroller "
    "reference manual (register maps, pin tables, electrical "
    "characteristics). Underscores ('_') are part of real register and "
    "signal names ('SDRAMC_WPSR', 'R8_USB_CTRL') — never add, delete, or "
    "move them.\n" + _CELL_RULES
)
GENERAL_CELL_PROMPT = _CELL_RULES
