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


class Metric(BaseModel):
    """A computed, publication-ready figure for one series in a note."""

    series_id: str
    label: str
    value: float
    unit: str
    as_of: date
    change: float | None = None
    stale: bool = False
    stale_as_of: date | None = None


class NoteFacts(BaseModel):
    """The complete, validated payload handed to an LLM call as its only input."""

    note_date: date
    metrics: list[Metric] = Field(min_length=1)


class NoteNarrative(BaseModel):
    """The only output an LLM call returns: prose fields, no numeric fields."""

    headline: str
    summary: str
    bullets: list[str] = Field(min_length=1)
