"""Numeric fidelity guard: verifies every numeral in a TickerNarrative traces to an EquitySnapshot.

Enforces CLAUDE.md's core invariant mechanically: "every numeral in the output
must be traceable to the input payload. If it is not, the run fails and
publishes nothing." This module never publishes anything itself -- it only
detects and (via check_numeric_fidelity) raises. The caller decides what
"fails" means operationally.

This is a near-verbatim duplicate of apps.macro_note.guards. Per CLAUDE.md's
rule of three, this is only the second numeric-fidelity guard (comps' guard is
structural, a different concern), not the third, so core/ stays empty and the
duplication is correct and accepted until a third real use demonstrates the
shared need. The matching engine below -- extract_numerals and its helpers,
_is_traceable, the regexes, the tolerance -- is byte-for-byte macro_note's, and
its exhaustive test coverage lives in tests/apps/macro_note/test_guards.py.
What changed for this system:

- The narrative has a headline and a summary, no bullets (a macro note itemizes
  genuinely separate topics; one ticker's ~7 figures form one story). This is
  fewer text fields to scan, nothing structural.
- EquitySnapshot is flat: one snapshot per ticker, with no sections, curve
  slopes, or FX-carry sub-lists. So _payload_candidates is a straight walk of
  one object's fields, not the nested section iteration macro_note needs.
- EquitySnapshot carries no change/horizon figures at all (no MetricChange
  equivalent -- this app has no history layer). A macro note legitimately
  quotes a computed 1d/1w/1m change; here, any narrated difference between two
  payload figures is by construction a fabrication, and the guard catches it
  because the derived number is in no payload field.
- market_cap is a raw integer (340878950400); it is added as a plain candidate,
  so a verbatim restatement ("340,878,950,400") traces via the comma-thousands
  branch of the digit regex. market_cap_display is the single canonical scaled
  form ("AUD 340.88 billion"), computed once in payload.py and added here as
  text, so its "340.88" is a legitimate candidate. A model-side rescale to any
  other rounding ("A$341 billion") is correctly blocked. There is deliberately
  no magnitude-scaling logic in this guard: rounding lives in exactly one place.
- The four margin/ROE fields are percent-tagged; trailing_pe, forward_pe, and
  enterprise_to_ebitda are unit-unspecified multiples ("x", not "%"). This is
  what stops a narrated "operating margin of 24.76%" tracing when 24.76 is in
  fact the trailing P/E.

Scope: this guard verifies TRACEABILITY, not ATTRIBUTION. It confirms a
narrated numeral's value (and, where the narrative marks a unit, its unit)
matches some real figure the model was given. It does not verify that the
figure is attached to the right metric -- a narrative that correctly quotes
24.76 but calls it the forward rather than the trailing P/E passes this guard.
That is a materially harder, open-ended correctness problem, not a numeric
fidelity one.

Matching algorithm, in one paragraph: every numeral in the narrative's text
fields is parsed (digit form, e.g. "24.76", and word form for zero through
twenty, e.g. "two") along with a unit tag inferred from the text immediately
following it ("%"/"percent" -> percent, "bp"/"basis points" -> basis_points,
otherwise -> unspecified). The same parser runs over EquitySnapshot's own
string fields (ticker, company_name, sector, currency, market_cap_display,
data_warnings), since those are literal text the model was given. Every typed
numeric field (current_price, market_cap, the three ValuationMultiples fields,
the four ProfitabilityMetrics fields) is added directly as a float, tagged by
field semantics; as_of contributes its year and day-of-month. A percent-tagged
or basis-point-tagged narrated numeral must match a same-tagged payload
candidate; an unspecified (unit-less) narrated numeral may match any payload
candidate regardless of tag. An EquitySnapshot never produces a basis-point
candidate, but the bucket is kept so a narrative that editorializes "widened
200 basis points" still fails against an empty pool.

ISO dates ("2026-08-24") are recognized as a unit before the generic digit
scan runs, and contribute year and day-of-month as unspecified numerals --
never a month numeral, since no payload field carries a bare month number to
check it against. This mirrors month-name dates ("August 24"), which likewise
only ever yield day and year. Without this special case, the generic digit/sign
regex reads a date's separator hyphens as minus signs, which was a real false
positive in macro_note's production (#21).

Known, accepted limitations (deliberate tradeoffs, carried over from
macro_note's guard unchanged):

- Sign-stripped magnitudes are accepted one-directionally: a payload value of
  -5.0 accepts a narrated "5.0", but a payload value of +5.0 never accepts a
  narrated "-5.0".
- An unspecified (unit-less) narrated numeral matches ANY payload candidate,
  including percent-tagged ones. A wholly invented, unit-less small number can
  coincidentally match an unrelated payload figure. This is accepted rather
  than fixed by matching unspecified numerals only against unspecified payload
  candidates, because that stricter rule would frequently false-block correct
  day-of-month, year, and price references, which have no natural unit.
- Word-form numbers are recognized for "zero" through "twenty" only.
  Hyphenated compounds ("twenty-five") are excluded entirely rather than
  decomposed into parts that might coincidentally match.
"""

import math
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.equity_snapshot.calculations import ProfitabilityMetrics, ValuationMultiples
from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import EquitySnapshot

NumeralUnit = Literal["percent", "basis_points", "unspecified"]

# Word-number range: zero through twenty. See module docstring for why this
# isn't extended further.
_WORD_NUMBERS: dict[str, int] = {
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

_SIGN_WORD_RE = re.compile(r"(?:^|\W)(?:negative|minus)\s*$", re.IGNORECASE)

_DIGIT_NUMBER_RE = re.compile(r"(?P<sign>-\s*)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")

# Matches ISO 8601 dates ("2026-08-24") so extract_numerals can claim the whole
# span before the generic digit/sign scan reaches it -- see extract_numerals'
# docstring for why this exists. Month/day ranges are restricted (01-12,
# 01-31) so this only fires on genuine dates, not arbitrary N-N-N tokens.
_ISO_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12]\d|3[01])(?!\d)"
)

# (?<!-) / (?!-) exclude hyphenated compounds ("twenty-five") from matching at all --
# see the module docstring's word-number limitation for why decomposing them into
# separate pieces ("twenty" + "five") would be actively wrong, not just incomplete.
_WORD_NUMBER_RE = re.compile(
    r"(?<!-)\b(?P<word>" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\b(?!-)",
    re.IGNORECASE,
)

_PERCENT_UNIT_RE = re.compile(r"^\s*(?:%|percent(?:age)?(?:\s+points?)?\b)", re.IGNORECASE)
_BASIS_POINT_UNIT_RE = re.compile(r"^\s*(?:bps?\b|basis\s+points?\b)", re.IGNORECASE)

_UNIT_LOOKAHEAD_CHARS = 30

# Assumes a sign word (e.g. "negative", "minus") directly or near-directly
# precedes the number it modifies. A sign word further away is not associated
# with the number, which is then treated as positive.
_SIGN_LOOKBEHIND_CHARS = 12

# Sized to absorb floating-point round-trip noise from calculations.py's
# arithmetic (differences on the order of 1e-14) while remaining far tighter
# than any genuine rounding or reformatting difference this guard exists to
# catch. This is not a rounding allowance: two genuinely different values must
# still fail.
_FLOAT_TOLERANCE = 1e-9


class NumeralMatch(BaseModel):
    """One numeral found in text, with its parsed value and inferred unit."""

    model_config = ConfigDict(frozen=True)

    text: str
    value: float
    unit: NumeralUnit


def extract_numerals(text: str) -> list[NumeralMatch]:
    """Find every digit-form and word-form (zero-twenty) numeral in `text`.

    Each match carries a unit inferred from the text immediately following it:
    "%"/"percent"/"percentage point(s)" -> percent, "bp"/"bps"/"basis point(s)" ->
    basis_points, otherwise -> unspecified. A "negative"/"minus" immediately
    before the numeral makes it negative.

    ISO dates ("2026-08-24") are recognized before the generic digit scan and
    claim their own span: they contribute year and day-of-month as unspecified
    numerals (mirroring how a month-name date like "August 24" only ever yields
    day and year), but never a month numeral. Without this, the generic
    digit/sign regex reads a date's separator hyphens as minus signs.
    """
    matches: list[NumeralMatch] = []
    consumed_spans: list[tuple[int, int]] = []
    for date_match in _ISO_DATE_RE.finditer(text):
        consumed_spans.append(date_match.span())
        matches.append(
            NumeralMatch(
                text=date_match.group("year"),
                value=float(date_match.group("year")),
                unit="unspecified",
            )
        )
        matches.append(
            NumeralMatch(
                text=date_match.group("day"),
                value=float(date_match.group("day")),
                unit="unspecified",
            )
        )
    for digit_match in _DIGIT_NUMBER_RE.finditer(text):
        if _overlaps_any(digit_match.span(), consumed_spans):
            continue
        raw = digit_match.group("num").replace(",", "")
        value = float(raw)
        if digit_match.group("sign") or _has_preceding_sign_word(text, digit_match.start()):
            value = -value
        matches.append(
            NumeralMatch(
                text=digit_match.group(0),
                value=value,
                unit=_detect_unit(text, digit_match.end()),
            )
        )
    for word_match in _WORD_NUMBER_RE.finditer(text):
        value = float(_WORD_NUMBERS[word_match.group("word").lower()])
        if _has_preceding_sign_word(text, word_match.start()):
            value = -value
        matches.append(
            NumeralMatch(
                text=word_match.group(0),
                value=value,
                unit=_detect_unit(text, word_match.end()),
            )
        )
    return matches


def _detect_unit(text: str, end: int) -> NumeralUnit:
    tail = text[end : end + _UNIT_LOOKAHEAD_CHARS]
    if _PERCENT_UNIT_RE.match(tail):
        return "percent"
    if _BASIS_POINT_UNIT_RE.match(tail):
        return "basis_points"
    return "unspecified"


def _has_preceding_sign_word(text: str, start: int) -> bool:
    head = text[max(0, start - _SIGN_LOOKBEHIND_CHARS) : start]
    return bool(_SIGN_WORD_RE.search(head))


def _overlaps_any(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and end > other_start for other_start, other_end in spans)


def _payload_candidates(snapshot: EquitySnapshot) -> dict[NumeralUnit, set[float]]:
    candidates: dict[NumeralUnit, set[float]] = {
        "percent": set(),
        "basis_points": set(),
        "unspecified": set(),
    }
    _add_text(candidates, snapshot.ticker)
    _add_text(candidates, snapshot.company_name)
    if snapshot.sector is not None:
        _add_text(candidates, snapshot.sector)
    _add_text(candidates, snapshot.currency)
    if snapshot.market_cap_display is not None:
        _add_text(candidates, snapshot.market_cap_display)
    _add_date(candidates, snapshot.as_of)
    _add_numeric(candidates, "unspecified", snapshot.current_price)
    _add_numeric(candidates, "unspecified", snapshot.market_cap)
    _add_valuation(candidates, snapshot.valuation)
    _add_profitability(candidates, snapshot.profitability)
    for warning in snapshot.data_warnings:
        _add_text(candidates, warning)
    return candidates


def _add_valuation(
    candidates: dict[NumeralUnit, set[float]], valuation: ValuationMultiples
) -> None:
    # P/E and EV/EBITDA are "x" multiples, not percentages -> unit-unspecified.
    _add_numeric(candidates, "unspecified", valuation.trailing_pe)
    _add_numeric(candidates, "unspecified", valuation.forward_pe)
    _add_numeric(candidates, "unspecified", valuation.enterprise_to_ebitda)


def _add_profitability(
    candidates: dict[NumeralUnit, set[float]], profitability: ProfitabilityMetrics
) -> None:
    # Margins and ROE are percent-scale (e.g. 43.34 means 43.34%) -> percent.
    _add_numeric(candidates, "percent", profitability.gross_margin_pct)
    _add_numeric(candidates, "percent", profitability.operating_margin_pct)
    _add_numeric(candidates, "percent", profitability.profit_margin_pct)
    _add_numeric(candidates, "percent", profitability.return_on_equity_pct)


def _add_numeric(
    candidates: dict[NumeralUnit, set[float]], unit: NumeralUnit, value: float | int | None
) -> None:
    if value is None:
        return
    v = float(value)
    candidates[unit].add(v)
    if v < 0:
        # One-directional sign-stripping: a negative payload value also accepts
        # its positive magnitude. See module docstring.
        candidates[unit].add(abs(v))


def _add_date(candidates: dict[NumeralUnit, set[float]], value: date | None) -> None:
    # datetime is a subclass of date; .year and .day work for both. Only year
    # and day are added -- never month, mirroring macro_note (no payload field
    # carries a bare month number to trace it against).
    if value is None:
        return
    candidates["unspecified"].add(float(value.year))
    candidates["unspecified"].add(float(value.day))


def _add_text(candidates: dict[NumeralUnit, set[float]], text: str) -> None:
    for numeral in extract_numerals(text):
        candidates[numeral.unit].add(numeral.value)
        if numeral.value < 0:
            candidates[numeral.unit].add(abs(numeral.value))


def _is_traceable(numeral: NumeralMatch, candidates: dict[NumeralUnit, set[float]]) -> bool:
    if numeral.unit == "unspecified":
        pool = candidates["percent"] | candidates["basis_points"] | candidates["unspecified"]
    else:
        pool = candidates[numeral.unit]
    return any(
        math.isclose(numeral.value, candidate, rel_tol=_FLOAT_TOLERANCE, abs_tol=_FLOAT_TOLERANCE)
        for candidate in pool
    )


class UntraceableNumeral(BaseModel):
    """One numeral in a TickerNarrative that could not be traced to an EquitySnapshot."""

    model_config = ConfigDict(frozen=True)

    text: str
    value: float
    unit: NumeralUnit
    source_field: str


class NumericFidelityError(RuntimeError):
    """Raised when a TickerNarrative has a numeral that cannot be traced to its EquitySnapshot."""


def find_untraceable_numerals(
    narrative: TickerNarrative, snapshot: EquitySnapshot
) -> list[UntraceableNumeral]:
    """Return every numeral in `narrative` that cannot be traced to `snapshot`.

    An empty list means the narrative is fully traceable. See the module
    docstring for exactly what "traceable" means and its documented limits.
    """
    candidates = _payload_candidates(snapshot)
    fields: list[tuple[str, str]] = [
        ("headline", narrative.headline),
        ("summary", narrative.summary),
    ]

    untraceable: list[UntraceableNumeral] = []
    for source_field, text in fields:
        for numeral in extract_numerals(text):
            if not _is_traceable(numeral, candidates):
                untraceable.append(
                    UntraceableNumeral(
                        text=numeral.text,
                        value=numeral.value,
                        unit=numeral.unit,
                        source_field=source_field,
                    )
                )
    return untraceable


def check_numeric_fidelity(narrative: TickerNarrative, snapshot: EquitySnapshot) -> None:
    """Raise NumericFidelityError if any numeral in `narrative` cannot be traced to `snapshot`.

    Callers must not publish `narrative` unless this returns without raising --
    this is the one CLAUDE.md invariant with no fallback: on failure, publish nothing.
    """
    untraceable = find_untraceable_numerals(narrative, snapshot)
    if not untraceable:
        return
    details = "; ".join(
        f'"{numeral.text}" ({numeral.value:g}, {numeral.unit}) in {numeral.source_field}'
        for numeral in untraceable
    )
    raise NumericFidelityError(f"Untraceable numeral(s) in narrative: {details}")
