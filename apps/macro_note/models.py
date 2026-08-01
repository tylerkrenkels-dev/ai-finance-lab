"""Pydantic data contracts for the Macro Research Digest.

These models are the layer boundary contract described in CLAUDE.md: connectors
produce Observations, calculations produce Metrics, and NoteFacts is the only
input an LLM call ever receives. NoteNarrative is the only output an LLM call
ever returns, and it carries prose fields only — no numeric fields, so the
numeric fidelity guard has a clean payload to check narrative numerals against.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SeriesSource = Literal["fred", "rba", "yfinance"]
SeriesCategory = Literal["rates", "inflation", "fx", "commodities", "equities"]


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


class CurveSlope(BaseModel):
    """A basis-point curve slope or cross-country spread, e.g. US 2s10s.

    Mirrors calculations.rates.Spread's shape; defined here for the same
    layering reason as MetricChange.
    """

    label: str
    spread_bp: float | None
    first_as_of: date | None
    second_as_of: date | None


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
    bullets: list[str] = Field(min_length=1)
