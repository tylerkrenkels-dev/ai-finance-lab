"""Structural fidelity guard: verifies every cell in a ComparableTransactionsTable
traces to a frozen raw-text excerpt of the real filing it was transcribed from.

This is the inversion of macro_note's numeric fidelity guard, for a different
failure mode. macro_note's guard checks LLM-generated prose against
Python-computed numbers, because the risk there is model hallucination. There
is no LLM output in apps/comps -- the risk here is transcription error: a
hand-typed (or Claude-typed) digit swap, a row copied from the wrong table, a
footnote definition mistyped while editing registry.py later. So this guard
checks the direction that actually matters for this system: structured data
against the frozen source text it was supposedly transcribed from.

Scope: this guard verifies TRACEABILITY of registry.py's data to its fixture,
not the fixture's own accuracy against the live filing. That verification
happened once, by hand, during investigation (cross-checked against a fresh,
uncached live re-fetch) -- the same trust boundary macro_note/registry.py uses
for RBA series codes. This guard exists to catch DRIFT after that point: an
edit to registry.py that isn't reflected in its fixture, or vice versa.

Matching algorithm: every checked value is normalized (all whitespace,
including non-breaking space, collapsed to a single regular space) and then
checked as a substring of the table's excerpt, normalized the same way.
Curly quotes, em-dashes, and every other character are matched exactly, not
normalized further -- the registry preserves those verbatim on purpose (see
models.py's module docstring), so a straightened quote should fail to match,
not silently pass. A multiple's None value (a blank/dash cell) is skipped
entirely: the model stores absence as None, not as a printed dash character,
so there is nothing to trace for that cell.
"""

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from apps.comps.models import ComparableTransactionsTable

_WHITESPACE_RE = re.compile(r"\s+")

_FIXTURES_ROOT = Path(__file__).parent


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


class UntraceableCell(BaseModel):
    """One value in a ComparableTransactionsTable that could not be traced to its excerpt."""

    model_config = ConfigDict(frozen=True)

    table_id: str
    field: str
    value: str


class StructuralFidelityError(RuntimeError):
    """Raised when a ComparableTransactionsTable contains a value untraceable to its excerpt."""


def find_untraceable_cells(
    table: ComparableTransactionsTable, raw_excerpt: str
) -> list[UntraceableCell]:
    """Return every value in `table` that cannot be traced to `raw_excerpt`.

    An empty list means every checked value is traceable. See the module
    docstring for exactly what "traceable" means and its documented scope.
    """
    normalized_excerpt = _normalize(raw_excerpt)
    untraceable: list[UntraceableCell] = []

    def check(field: str, value: str) -> None:
        if _normalize(value) not in normalized_excerpt:
            untraceable.append(UntraceableCell(table_id=table.table_id, field=field, value=value))

    for i, row in enumerate(table.rows):
        # target is included in the row prefix itself so a maintainer scanning a
        # 68-row table can jump straight to the right row instead of counting
        # indices by hand.
        row_prefix = f"rows[{i}] ({row.target})"
        check(f"{row_prefix}.target", row.target)
        check(f"{row_prefix}.acquiror", row.acquiror)
        check(f"{row_prefix}.announcement_period_raw", row.announcement_period_raw)
        for label, value in row.multiples.items():
            if value is not None:
                check(f"{row_prefix}.multiples[{label!r}]", value)
        for ref in row.footnote_refs:
            check(f"{row_prefix}.footnote_refs[{ref!r}]", ref)

    for key, value in table.footnotes.items():
        check(f"footnotes[{key!r}]", value)

    if table.summary_stats:
        for stat_label, stat_values in table.summary_stats.items():
            check(f"summary_stats[{stat_label!r}] (label)", stat_label)
            for stat_key, stat_value in stat_values.items():
                check(f"summary_stats[{stat_label!r}][{stat_key!r}]", stat_value)

    return untraceable


def check_structural_fidelity(table: ComparableTransactionsTable, raw_excerpt: str) -> None:
    """Raise StructuralFidelityError if any value in `table` can't be traced to `raw_excerpt`.

    Callers must not publish `table` unless this returns without raising.
    """
    untraceable = find_untraceable_cells(table, raw_excerpt)
    if not untraceable:
        return
    details = "; ".join(f"{cell.field}={cell.value!r}" for cell in untraceable)
    raise StructuralFidelityError(f"Untraceable value(s) in {table.table_id}: {details}")


def load_raw_excerpt(table: ComparableTransactionsTable) -> str:
    """Read the frozen fixture text for `table` from apps/comps/<raw_excerpt_path>."""
    return (_FIXTURES_ROOT / table.source.raw_excerpt_path).read_text(encoding="utf-8")
