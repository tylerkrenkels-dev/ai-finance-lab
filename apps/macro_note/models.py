"""Pydantic data contracts for the Macro Research Digest.

These models are the layer boundary contract described in CLAUDE.md: connectors
produce Observations, calculations produce Metrics, and NoteFacts is the only
input an LLM call ever receives. NoteNarrative is the only output an LLM call
ever returns, and it carries prose fields only — no numeric fields, so the
numeric fidelity guard has a clean payload to check narrative numerals against.

MetricChange/Metric/CurveSlope/FxCarry round their float fields at construction
time (see each class's validators). This is deliberately not done in
calculations/ -- those modules compute from full, unrounded precision, and
rounding an intermediate result before using it in further arithmetic (e.g.
FxCarry.annualised_return_pct = rate_differential_pct + annualised_spot_change_pct)
would compound error. Rounding belongs exactly once, at the boundary where a
calculation's finished output becomes a publication-facing fact -- which is
here. Every downstream consumer (the render table, the narrative LLM, the
numeric fidelity guard) then sees the same already-clean number from a single
source of truth, rather than each formatting a raw float independently and
risking disagreeing with each other (found via #23's live dry run: a copper
price of 6.5304999351501465 read as "6.5305" in the rendered table but
"6.5304999351501465" in the narrative, for the same metric).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SeriesSource = Literal["fred", "rba", "yfinance"]
SeriesCategory = Literal["rates", "inflation", "fx", "commodities", "equities"]


def _round_or_none(value: float | None, digits: int) -> float | None:
    return value if value is None else round(value, digits)


class Observation(BaseModel):
    """A single raw data point fetched from a source for one series."""

    series_id: str
    value: float
    as_of: date
    fetched_at: datetime


class SeriesMeta(BaseModel):
    """Static registry metadata describing how to fetch and label a series."""

    series_id: str
    name: str
    source: SeriesSource
    source_code: str
    unit: str
    category: SeriesCategory


class MetricChange(BaseModel):
    """A percentage/basis-point change over one horizon, embedded in a Metric.

    Mirrors calculations.changes.Change's shape but is defined here, not
    imported from calculations/, to keep the dependency direction one-way:
    models.py is the foundational layer that calculations/ depends on, not
    the reverse. None fields mean that horizon couldn't be computed -- not
    zero, not an error.
    """

    pct_change: float | None
    bp_change: float | None
    reference_as_of: date | None

    @field_validator("pct_change")
    @classmethod
    def _round_pct_change(cls, v: float | None) -> float | None:
        return _round_or_none(v, 2)

    @field_validator("bp_change")
    @classmethod
    def _round_bp_change(cls, v: float | None) -> float | None:
        return _round_or_none(v, 1)


class Metric(BaseModel):
    """A computed, publication-ready figure for one series in a note.

    as_of is always the real date of the underlying value, even when stale --
    a Monday note legitimately shows Friday's date for a bond yield without
    that meaning stale. stale_as_of mirrors as_of, but only when stale is
    True, as a convenience signal for a renderer that wants "the stale date"
    without also branching on the stale flag itself.
    """

    series_id: str
    label: str
    value: float
    unit: str
    as_of: date
    change_1d: MetricChange
    change_1w: MetricChange
    change_1m: MetricChange
    stale: bool = False
    stale_as_of: date | None = None

    @model_validator(mode="after")
    def _round_value(self) -> "Metric":
        self.value = round(self.value, 2 if self.unit == "%" else 4)
        return self


class CurveSlope(BaseModel):
    """A basis-point curve slope or cross-country spread, e.g. US 2s10s.

    Mirrors calculations.rates.Spread's shape; defined here for the same
    layering reason as MetricChange.
    """

    label: str
    spread_bp: float | None
    first_as_of: date | None
    second_as_of: date | None

    @field_validator("spread_bp")
    @classmethod
    def _round_spread_bp(cls, v: float | None) -> float | None:
        return _round_or_none(v, 1)


class FxCarry(BaseModel):
    """An AUD/USD policy-rate carry figure for one horizon.

    Mirrors calculations.fx.Carry's shape; defined here for the same
    layering reason as MetricChange.
    """

    label: str
    annualised_return_pct: float | None
    rate_differential_pct: float | None
    annualised_spot_change_pct: float | None
    window_days: int | None

    @field_validator("annualised_return_pct", "rate_differential_pct", "annualised_spot_change_pct")
    @classmethod
    def _round_pct_fields(cls, v: float | None) -> float | None:
        return _round_or_none(v, 2)


class Section(BaseModel):
    """A named grouping of Metrics and derived figures for the note.

    One section per SeriesMeta.category (e.g. "Rates", "FX"), so a curve
    slope derived from two rates series lives alongside the individual
    rate Metrics it was computed from, and similarly for FX carry.
    """

    title: str
    metrics: list[Metric] = Field(default_factory=list)
    curve_slopes: list[CurveSlope] = Field(default_factory=list)
    fx_carry: list[FxCarry] = Field(default_factory=list)


class NoteFacts(BaseModel):
    """The complete, validated payload handed to an LLM call as its only input."""

    note_date: date
    sections: list[Section] = Field(min_length=1)
    data_warnings: list[str] = Field(default_factory=list)


class NoteNarrative(BaseModel):
    """The only output an LLM call returns: prose fields, no numeric fields."""

    headline: str
    summary: str
    # max_length=9 per #44, revised after the commodities expansion (7-series
    # Commodities section, up from 3): #44 originally set this to 8, grounded in a
    # live run against the pre-expansion 5-section/12-series payload -- a clean
    # reproduction produced 7 bullets, a guard-failure run produced 14+. Two live
    # runs against the expanded 16-series payload (one with the new daily
    # commodities stale, one with them fresh) both landed at exactly 8 bullets --
    # zero headroom on two-for-two real, guard-passing runs, not a guess. 9 applies
    # the same "+1 over the observed clean count" margin #44 used originally. An
    # oversized response raises ValidationError at construction in
    # NarrativeGenerator.generate(), fails loud and publishes nothing -- the same
    # pattern as NumericFidelityError and NoDataAvailableError elsewhere in this
    # pipeline, not truncated or retried.
    bullets: list[str] = Field(min_length=1, max_length=9)
