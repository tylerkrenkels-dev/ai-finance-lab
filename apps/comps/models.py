"""Pydantic data contracts for the M&A Comparables reference.

This is a hand-curated reference, not a live scanner: `apps/comps` stores a fixed
set of real "Selected Transactions Analysis" (or equivalently named) tables,
transcribed once from real DEFM14A filings on SEC EDGAR, never re-fetched or
re-parsed at runtime. The guard module (a later issue) checks the transcribed
data in ComparableTransactionsTable against a frozen raw-text excerpt of the
actual filing, captured once by hand -- the same trust boundary macro_note's
registry.py uses for RBA series codes: verified once, documented, trusted
after that.

The row and table schema were deliberately NOT forced into one canonical shape.
Real investigation across 5 deals / 6 tables found genuine structural variance:
Qatalyst's Splunk table has 3 multiple columns, its ANSYS table has 1; Wells
Fargo's Norfolk Southern table has multiples inline plus footnotes and
mean/median rows baked into the table, its Chart Industries table has no
multiple column at all; Foot Locker's table has no per-row multiple, only a
separate summary-stats block. ComparableTransactionRow.multiples is therefore
an open dict keyed by the column label AS PRINTED in the source, not a fixed
set of named fields -- forcing e.g. "NTM Revenue Multiple" and "TEV/LTM EBITDA
Multiple" into the same field would claim two different measurements are the
same one. Announcement dates are stored as printed too (ComparableTransactionRow
.announcement_period_raw): sources use "07/31/23", "2021", "August 2024", and
"09/21" for the same concept, and coercing any of these to a full date invents
precision the source never gave. announcement_year is the one derived field,
because it is the one thing genuinely present in all four formats observed.
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DealStatus = Literal["pending", "completed"]

_ACCESSION_NUMBER_RE = r"^\d{10}-\d{2}-\d{6}$"
_CIK_RE = r"^\d{1,10}$"


class Deal(BaseModel):
    """One M&A transaction. A Deal can back more than one ComparableTransactionsTable --
    Norfolk Southern/Union Pacific has two, one per advisor, from the same filing."""

    deal_id: str
    target_name: str
    acquiror_name: str
    announced_date: date
    status: DealStatus
    completed_date: date | None = None

    @model_validator(mode="after")
    def _completed_date_matches_status(self) -> "Deal":
        if self.status == "completed" and self.completed_date is None:
            raise ValueError("completed_date is required when status is 'completed'")
        if self.status == "pending" and self.completed_date is not None:
            raise ValueError("completed_date must be None when status is 'pending'")
        return self


class FilingSource(BaseModel):
    """Provenance for one DEFM14A, hand-verified once against live EDGAR.

    accession_number and the two URLs are validated structurally here, at the
    layer boundary, because a malformed citation is a defect regardless of what
    the table's content turns out to be -- this is not the same check as the
    guard module's cell-to-excerpt fidelity check, which needs the external
    raw_excerpt_path fixture and so can't live in a Pydantic validator.
    """

    company_name: str
    cik: str
    accession_number: str
    document_url: str
    index_url: str
    filed_date: date
    section_heading: str
    approx_page_fraction: float = Field(ge=0.0, le=1.0)
    retrieved_at: date
    raw_excerpt_path: str

    @field_validator("cik")
    @classmethod
    def _cik_is_digits(cls, v: str) -> str:
        if not re.match(_CIK_RE, v):
            raise ValueError(f"cik must be 1-10 digits, got {v!r}")
        return v

    @field_validator("accession_number")
    @classmethod
    def _accession_number_format(cls, v: str) -> str:
        if not re.match(_ACCESSION_NUMBER_RE, v):
            raise ValueError(f"accession_number must match NNNNNNNNNN-NN-NNNNNN, got {v!r}")
        return v

    @field_validator("document_url", "index_url")
    @classmethod
    def _url_is_sec_gov(cls, v: str) -> str:
        if not v.startswith("https://www.sec.gov/"):
            raise ValueError(f"{v!r} is not a https://www.sec.gov/ URL")
        return v


class ComparableTransactionRow(BaseModel):
    """One precedent-transaction line from a comparable-transactions table.

    announcement_period_raw preserves the source's own precision exactly (see
    module docstring); announcement_year is the only value derived from it.
    multiples maps each column label as printed to its printed value, or None
    for a blank/dash cell -- values are NOT parsed to float here. This is a
    reference, not a calculator: nothing in this phase does arithmetic on these
    multiples, so parsing them would add a lossy conversion (which "x" suffix
    convention, which dash character means "not disclosed" vs "not applicable")
    with no consumer that needs it yet.
    """

    target: str
    acquiror: str
    announcement_period_raw: str
    announcement_year: int
    multiples: dict[str, str | None] = Field(default_factory=dict)
    footnote_refs: list[str] = Field(default_factory=list)


class ComparableTransactionsTable(BaseModel):
    """One bank's comparable-transactions (or -companies) table from one filing.

    expected_row_count is recorded independently, by counting the source table
    before transcription -- not derived from len(rows) after the fact -- so the
    construction-time check below is a genuine cross-check against a transcription
    error (a dropped or duplicated row), not a tautology.
    """

    table_id: str
    deal_id: str
    advisor: str
    analysis_label: str
    source: FilingSource
    multiple_columns: list[str] = Field(default_factory=list)
    rows: list[ComparableTransactionRow] = Field(min_length=1)
    expected_row_count: int
    footnotes: dict[str, str] = Field(default_factory=dict)
    summary_stats: dict[str, dict[str, str]] | None = None

    @model_validator(mode="after")
    def _row_count_matches_expected(self) -> "ComparableTransactionsTable":
        if len(self.rows) != self.expected_row_count:
            raise ValueError(
                f"{self.table_id}: expected_row_count={self.expected_row_count} "
                f"but rows has {len(self.rows)} entries"
            )
        return self

    @model_validator(mode="after")
    def _row_multiples_match_declared_columns(self) -> "ComparableTransactionsTable":
        declared = set(self.multiple_columns)
        for row in self.rows:
            undeclared = set(row.multiples) - declared
            if undeclared:
                raise ValueError(
                    f"{self.table_id}: row for {row.target!r} has multiple column(s) "
                    f"{sorted(undeclared)} not present in multiple_columns={self.multiple_columns}"
                )
        return self
