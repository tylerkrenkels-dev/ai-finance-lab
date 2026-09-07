"""The figure-token grammar shared by claim-text extraction and FIG construction.

A *figure* is a load-bearing numeral with a unit tag. The citation guard works
entirely in terms of ``(value, unit)`` set membership: a numeral in a claim is
verified by checking it against the figure set of the one page that claim cites.

Two entry points share one grammar:

- ``extract_figures(text)`` runs over prose -- claim text, and macro/equity
  ``data_warnings`` strings, which are literal text the model was shown.
- ``page_figures(page)`` / ``figure_set(page)`` build the FIG set of a SourcePage
  from its structured ``sections``. Typed tokens (``%`` / ``x`` / ``bp``) are
  taken wherever they appear in a cell; a bare number is taken only when the
  whole cell is a single numeric run wrapped in non-digit text ("USD 4.75
  trillion", "2023", "4,374.7002 USD/oz") -- which excludes accession numbers,
  CIKs, URLs and "07/31/23"-style raw announcement strings without a unit rule.

Unit tags are strict: ``percent``, ``multiple`` (an "x" multiple), ``basis_points``
and ``unspecified`` never match across each other. This is the opposite of the
macro/equity numeric-fidelity guards, which deliberately let an unspecified
numeral match anything; here exact-unit discrimination is the point (34.04% must
not clear against a 34.09x, 5.8x must not clear against 5.9x). The only
normalisation is trailing zeros, via ``float`` ("27.90x" == "27.9x"), because the
real published pages disagree with themselves on trailing zeros.

ISO dates (``YYYY-MM-DD``) claim their span and contribute nothing -- front-matter
and "As Of" dates are metadata, not computed quantities. A bare 4-digit year that
is genuine table data (a comps "Year" cell, "August 2024") still lands as an
``unspecified`` figure because it is a plain number, not an ISO date; that is
correct, since comps years are in scope for the guard.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.research_agent.models import SourcePage

FigureUnit = Literal["percent", "multiple", "basis_points", "unspecified"]

# Zero through twenty, digit-form only for compounds. A third verbatim copy of
# the map in apps.macro_note.guards / apps.equity_snapshot.guards: the rule of
# three is about extracting a *shared module*, and this grammar is not that one
# (strict unit tags, cell-aware, no payload model). Duplication stays until a
# real shared need is demonstrated, per CLAUDE.md.
WORD_NUMBERS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}

# Comps sections that carry provenance, not analysis: filing metadata, deal
# parties and footnote prose. Their numerals (CIK, accession fragments, "COVID-19")
# must never enter a figure set.
_SKIP_COMPS_HEADINGS = frozenset({"Deal", "Source", "Footnotes"})

# Macro columns whose cells are the note's own published deltas -- the only
# figures that may back a relational claim about a macro note.
_MACRO_DELTA_COLUMNS = frozenset({"1D", "1W", "1M"})
_MACRO_RELATIONAL_SECTION_SUFFIXES = ("/ Curve Slopes", "/ FX Carry")

_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)")
_DIGIT_RE = re.compile(r"(?P<sign>-\s*)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
_WORD_RE = re.compile(
    r"(?<!-)\b(?P<word>" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True)) + r")\b(?!-)",
    re.IGNORECASE,
)
_SIGN_WORD_RE = re.compile(r"(?:^|\W)(?:negative|minus)\s*$", re.IGNORECASE)

_PERCENT_RE = re.compile(r"^\s?(?:%|percent(?:age)?(?:\s+points?)?\b)", re.IGNORECASE)
_MULTIPLE_RE = re.compile(r"^[xX](?![A-Za-z0-9])")
_BASIS_POINT_RE = re.compile(r"^\s?(?:bps?\b|basis[\s-]points?\b)", re.IGNORECASE)

# A spelled cardinal ("three") counts as a figure only when it reads as a measured
# count -- "three consecutive sessions", "two straight weeks" -- not "the two
# companies" / "one of". Streak counts are the one place a research-agent claim
# carries a load-bearing spelled number (the fabricated-streak trap, trace 2A).
_STREAK_CONTEXT_RE = re.compile(
    r"^[\sA-Za-z]{0,20}\b(?:sessions?|days?|weeks?|months?|quarters?|years?|times?|"
    r"straight|consecutive|in\s+a\s+row|running)\b",
    re.IGNORECASE,
)

# The whole cell is a single numeric run with only non-digit text around it.
_BARE_CELL_RE = re.compile(r"[^\d]*?(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)[^\d]*")

_UNIT_LOOKAHEAD = 20
_SIGN_LOOKBEHIND = 12

# ``Figure.text`` carries the numeral with its unit in canonical short form, so a
# violation can quote "34.04%" / "5.8x" / "12bp" back to the model regardless of
# how the claim spelled the unit.
_CANONICAL_SUFFIX: dict[str, str] = {
    "percent": "%",
    "multiple": "x",
    "basis_points": "bp",
    "unspecified": "",
}


class Figure(BaseModel):
    """One numeral, its parsed value and its unit tag."""

    model_config = ConfigDict(frozen=True)

    text: str
    value: float
    unit: FigureUnit


def extract_figures(text: str) -> list[Figure]:
    """Every digit-form and word-form (zero-twenty) numeral in `text`, tagged.

    The unit is read from the characters immediately after the numeral: ``%`` /
    ``percent`` -> percent, an ``x`` touching the digits -> multiple, ``bp`` /
    ``basis points`` -> basis_points, otherwise unspecified. A ``-`` or a
    "negative"/"minus" just before the numeral makes it negative. ISO dates are
    consumed first and yield nothing.
    """
    figures: list[Figure] = []
    blocked = [m.span() for m in _ISO_DATE_RE.finditer(text)]

    for match in _DIGIT_RE.finditer(text):
        if any(match.start() < b_end and match.end() > b_start for b_start, b_end in blocked):
            continue
        digits = match.group("num")
        unit = _unit_after(text, match.end())
        if unit == "unspecified" and not _bare_number_is_load_bearing(digits):
            # A bare 1-3 digit integer in prose is almost always part of a label
            # or name ("2-year", "ASX 200", "2s10s", "UNIT4"), not a quantity.
            # Load-bearing bare numbers are decimals and 4-digit years.
            continue
        value = float(digits.replace(",", ""))
        if match.group("sign") or _preceding_sign_word(text, match.start()):
            value = -value
        figures.append(
            Figure(text=match.group(0) + _CANONICAL_SUFFIX[unit], value=value, unit=unit)
        )

    for match in _WORD_RE.finditer(text):
        if not _STREAK_CONTEXT_RE.match(text[match.end() :]):
            continue
        unit = _unit_after(text, match.end())
        value = float(WORD_NUMBERS[match.group("word").lower()])
        if _preceding_sign_word(text, match.start()):
            value = -value
        figures.append(
            Figure(text=match.group("word") + _CANONICAL_SUFFIX[unit], value=value, unit=unit)
        )

    return figures


def page_figures(page: SourcePage) -> list[Figure]:
    """Every figure present on `page`: its structured cells plus its data warnings.

    From each cell, typed tokens (``%`` / ``x`` / ``bp``) wherever they occur; a
    bare unspecified number only when the whole cell is one numeric run (see
    ``_BARE_CELL_RE``). Data-warning strings are prose and contribute every
    numeral, since the model was shown them verbatim.
    """
    figures: list[Figure] = []
    for section in page.sections:
        if page.system == "comps" and section.heading in _SKIP_COMPS_HEADINGS:
            continue
        for row in section.rows:
            for value in row.values():
                figures.extend(_cell_figures(value))
    for warning in page.data_warnings:
        figures.extend(extract_figures(warning))
    return figures


def figure_set(page: SourcePage) -> set[tuple[float, FigureUnit]]:
    """FIG(page): the ``(value, unit)`` set every cited numeral is checked against."""
    return _key_set(page_figures(page))


def relational_allowlist(page: SourcePage) -> set[tuple[float, FigureUnit]]:
    """Figures on `page` that may back a relational or "change" claim.

    macro_note: cells under 1D / 1W / 1M columns, plus every figure in the Curve
    Slopes and FX Carry sections (all derived, single-note quantities). Equity
    snapshots and comps tables carry no time dimension -> empty, so any "rose" /
    "above" / "cumulatively" about their figures is agent computation.
    """
    if page.system != "macro_note":
        return set()
    figures: list[Figure] = []
    for section in page.sections:
        if section.heading.endswith(_MACRO_RELATIONAL_SECTION_SUFFIXES):
            for row in section.rows:
                for value in row.values():
                    figures.extend(_cell_figures(value))
        elif section.heading.endswith("/ Metrics"):
            for row in section.rows:
                for column, value in row.items():
                    if column in _MACRO_DELTA_COLUMNS:
                        figures.extend(extract_figures(value))
    return _key_set(figures)


def _cell_figures(value: str) -> list[Figure]:
    typed = [f for f in extract_figures(value) if f.unit != "unspecified"]
    if typed:
        return typed
    match = _BARE_CELL_RE.fullmatch(value.strip())
    if match is None or not _bare_number_is_load_bearing(match.group("num")):
        # Rejects label cells like "AU 3-Year Government Bond Yield" -- the bare
        # "3" is not a figure. Keeps decimals and 4-digit years.
        return []
    return [
        Figure(
            text=value.strip(),
            value=float(match.group("num").replace(",", "")),
            unit="unspecified",
        )
    ]


def _key_set(figures: list[Figure]) -> set[tuple[float, FigureUnit]]:
    keys: set[tuple[float, FigureUnit]] = set()
    for figure in figures:
        keys.add((round(figure.value, 9), figure.unit))
        if figure.value < 0:
            # One-directional: a negative published figure also clears its
            # positive magnitude (direction is carried by words in the claim).
            keys.add((round(-figure.value, 9), figure.unit))
    return keys


def _bare_number_is_load_bearing(digits: str) -> bool:
    """A bare (unit-less) numeral matters only as a decimal or a 4-digit year."""
    if "." in digits:
        return True
    plain = digits.replace(",", "")
    return plain.isdigit() and len(plain) == 4 and 1900 <= int(plain) <= 2099


def _unit_after(text: str, end: int) -> FigureUnit:
    tail = text[end : end + _UNIT_LOOKAHEAD]
    if _PERCENT_RE.match(tail):
        return "percent"
    if _MULTIPLE_RE.match(tail):
        return "multiple"
    if _BASIS_POINT_RE.match(tail):
        return "basis_points"
    return "unspecified"


def _preceding_sign_word(text: str, start: int) -> bool:
    return bool(_SIGN_WORD_RE.search(text[max(0, start - _SIGN_LOOKBEHIND) : start]))
