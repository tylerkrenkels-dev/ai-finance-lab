"""Numeric fidelity guard: verifies every numeral in a NoteNarrative traces to NoteFacts.

Enforces CLAUDE.md's core invariant mechanically: "every numeral in the output
must be traceable to the input payload. If it is not, the run fails and
publishes nothing." This module never publishes anything itself -- it only
detects and (via check_numeric_fidelity) raises. The caller decides what
"fails" means operationally.

Scope: this guard verifies TRACEABILITY, not ATTRIBUTION. It confirms a
narrated numeral's value (and, where the narrative marks a unit, its unit)
matches some real figure the model was given. It does not verify that the
figure is attached to the right metric or timeframe -- a narrative that
correctly quotes 4.28 but claims it is next week's forecast rather than
today's yield will pass this guard. That is a materially harder, open-ended
correctness problem, not a numeric fidelity one.

Matching algorithm, in one paragraph: every numeral in the narrative's text
fields is parsed (digit form, e.g. "4.28", and word form for zero through
twenty, e.g. "two") along with a unit tag inferred from the text immediately
following it ("%"/"percent" -> percent, "bp"/"basis points" -> basis_points,
otherwise -> unspecified). The same parser runs over NoteFacts's own string
fields (data_warnings, labels, titles), since those are literal text the
model was given. Every typed numeric field in NoteFacts (Metric.value,
MetricChange.pct_change/bp_change, CurveSlope.spread_bp, FxCarry's percentage
and window_days fields) is added directly as a float, tagged by field
semantics; every date field contributes its year and day-of-month. A
percent-tagged or basis-point-tagged narrated numeral must match a
same-tagged payload candidate; an unspecified (unit-less) narrated numeral
may match any payload candidate regardless of tag.

ISO dates ("2026-08-07") are recognized as a unit before the generic digit
scan runs, and contribute year and day-of-month as unspecified numerals --
never a month numeral, since no payload field carries a bare month number to
check it against. This mirrors month-name dates ("July 31"), which likewise
only ever yield day and year: "July" isn't a digit token, so no month numeral
is produced there either. Without this special case, the generic digit/sign
regex reads a date's separator hyphens as minus signs (e.g. "2026-08-07"
splitting into 2026, -08, -07), which is exactly the false positive this
guard hit in production on a real, correctly-cited date (#21).

Known, accepted limitations (deliberate tradeoffs, not bugs):

- Sign-stripped magnitudes are accepted one-directionally: a payload value
  of -5.0 accepts a narrated "5.0" (direction expressed in words, per #19's
  live-observed finding), but a payload value of +5.0 never accepts a
  narrated "-5.0". Flipping this the other way would let a genuinely wrong
  sign through.
- An unspecified (unit-less) narrated numeral matches ANY payload candidate,
  including percent- and basis-point-tagged ones. This means a genuinely
  fabricated, unit-less small number can coincidentally match an unrelated
  payload figure and pass as a false negative -- e.g. if bp_change happens
  to be 2.0 somewhere in the payload, a wholly invented, unit-less claim
  like "2 major central bank meetings this week" would trace. This is
  accepted rather than fixed by matching unspecified numerals only against
  unspecified payload candidates, because that stricter rule would create
  the opposite, more common problem: legitimate day-of-month, year, and
  index-level references -- which have no natural unit -- would need to
  land in exactly the right bucket by coincidence, producing frequent false
  blocks on correct narratives. The guard is deliberately strongest exactly
  where a wrong number is most misleading -- percentages and basis points --
  and loosest where a coincidental match is lowest-stakes.
- Word-form numbers are recognized for "zero" through "twenty" only, per
  #19's live-observed spelled-out case ("two"). This is not expanded to
  cover larger spelled-out numbers (e.g. a multi-week outage narrated as
  "forty-five days ago") because financial/professional writing convention,
  and the narrative system prompt itself, both push toward digit form well
  before twenty. Hyphenated compounds ("twenty-five", "thirty-one") are
  deliberately excluded from word-number matching entirely, rather than
  decomposed into their parts -- "twenty-five" does NOT extract as two
  separate matches "twenty" and "five", which would let a genuinely wrong
  compound number slip through if either piece coincidentally matched some
  unrelated payload value. A number spelled out above twenty simply
  contributes no numeral for the guard to check, which is a safer default
  than a spurious partial match.
"""

import math
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.macro_note.models import CurveSlope, FxCarry, Metric, NoteFacts, NoteNarrative

NumeralUnit = Literal["percent", "basis_points", "unspecified"]

# Word-number range: zero through twenty, per #19's live-observed spelled-out case
# ("two" for a value of 2). See module docstring for why this isn't extended further.
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

# Matches ISO 8601 dates ("2026-08-07") so extract_numerals can claim the whole
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

# Assumes a sign word (e.g. "negative", "minus") directly or near-directly precedes
# the number it modifies -- the phrasing observed in #19 ("negative 43.0 basis
# points"). A sign word further away than this is not associated with the number,
# which is then treated as positive; since a negative payload value's positive
# magnitude is already an accepted match (see _add_numeric), this only matters if a
# narrated numeral's *sign* genuinely contradicts the payload while its *magnitude*
# is correct and real -- a narrower case than the guard's core job of catching
# wrong magnitudes and fabricated figures.
_SIGN_LOOKBEHIND_CHARS = 12

# Sized to absorb floating-point round-trip noise from calculations.py's arithmetic
# (differences on the order of 1e-14, e.g. 0.46999999999999997 vs the "intended"
# 0.47) while remaining far tighter than any genuine rounding or reformatting
# difference this guard exists to catch (4.3 vs 4.25 is a gap of 0.05 -- fourteen
# orders of magnitude looser than this tolerance). This is not a rounding
# allowance: two genuinely different values must still fail.
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

    ISO dates ("2026-08-07") are recognized before the generic digit scan and
    claim their own span: they contribute year and day-of-month as unspecified
    numerals (mirroring how a month-name date like "July 31" only ever yields
    day and year), but never a month numeral. Without this, the generic
    digit/sign regex reads a date's separator hyphens as minus signs -- e.g.
    "2026-08-07" would otherwise split into 2026, -08, -07 -- which is exactly
    the false positive this guard hit in production (#21).
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


def _payload_candidates(facts: NoteFacts) -> dict[NumeralUnit, set[float]]:
    candidates: dict[NumeralUnit, set[float]] = {
        "percent": set(),
        "basis_points": set(),
        "unspecified": set(),
    }
    _add_date(candidates, facts.note_date)
    for warning in facts.data_warnings:
        _add_text(candidates, warning)
    for section in facts.sections:
        _add_text(candidates, section.title)
        for metric in section.metrics:
            _add_metric(candidates, metric)
        for slope in section.curve_slopes:
            _add_curve_slope(candidates, slope)
        for carry in section.fx_carry:
            _add_fx_carry(candidates, carry)
    return candidates


def _add_metric(candidates: dict[NumeralUnit, set[float]], metric: Metric) -> None:
    _add_text(candidates, metric.label)
    value_unit: NumeralUnit = "percent" if metric.unit == "%" else "unspecified"
    _add_numeric(candidates, value_unit, metric.value)
    _add_date(candidates, metric.as_of)
    _add_date(candidates, metric.stale_as_of)
    for change in (metric.change_1d, metric.change_1w, metric.change_1m):
        _add_numeric(candidates, "percent", change.pct_change)
        _add_numeric(candidates, "basis_points", change.bp_change)
        _add_date(candidates, change.reference_as_of)


def _add_curve_slope(candidates: dict[NumeralUnit, set[float]], slope: CurveSlope) -> None:
    _add_text(candidates, slope.label)
    _add_numeric(candidates, "basis_points", slope.spread_bp)
    _add_date(candidates, slope.first_as_of)
    _add_date(candidates, slope.second_as_of)


def _add_fx_carry(candidates: dict[NumeralUnit, set[float]], carry: FxCarry) -> None:
    _add_text(candidates, carry.label)
    _add_numeric(candidates, "percent", carry.annualised_return_pct)
    _add_numeric(candidates, "percent", carry.rate_differential_pct)
    _add_numeric(candidates, "percent", carry.annualised_spot_change_pct)
    _add_numeric(candidates, "unspecified", carry.window_days)


def _add_numeric(
    candidates: dict[NumeralUnit, set[float]], unit: NumeralUnit, value: float | int | None
) -> None:
    if value is None:
        return
    v = float(value)
    candidates[unit].add(v)
    if v < 0:
        # One-directional sign-stripping: a negative payload value also accepts its
        # positive magnitude (direction expressed in words). See module docstring.
        candidates[unit].add(abs(v))


def _add_date(candidates: dict[NumeralUnit, set[float]], value: date | None) -> None:
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
    """One numeral in a NoteNarrative that could not be traced to NoteFacts."""

    model_config = ConfigDict(frozen=True)

    text: str
    value: float
    unit: NumeralUnit
    source_field: str


class NumericFidelityError(RuntimeError):
    """Raised when a NoteNarrative contains a numeral that cannot be traced to NoteFacts."""


def find_untraceable_numerals(
    narrative: NoteNarrative, facts: NoteFacts
) -> list[UntraceableNumeral]:
    """Return every numeral in `narrative` that cannot be traced to `facts`.

    An empty list means the narrative is fully traceable. See the module
    docstring for exactly what "traceable" means and its documented limits.
    """
    candidates = _payload_candidates(facts)
    fields: list[tuple[str, str]] = [
        ("headline", narrative.headline),
        ("summary", narrative.summary),
        *((f"bullets[{i}]", bullet) for i, bullet in enumerate(narrative.bullets)),
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


def check_numeric_fidelity(narrative: NoteNarrative, facts: NoteFacts) -> None:
    """Raise NumericFidelityError if any numeral in `narrative` cannot be traced to `facts`.

    Callers must not publish `narrative` unless this returns without raising --
    this is the one CLAUDE.md invariant with no fallback: on failure, publish nothing.
    """
    untraceable = find_untraceable_numerals(narrative, facts)
    if not untraceable:
        return
    details = "; ".join(
        f'"{numeral.text}" ({numeral.value:g}, {numeral.unit}) in {numeral.source_field}'
        for numeral in untraceable
    )
    raise NumericFidelityError(f"Untraceable numeral(s) in narrative: {details}")
