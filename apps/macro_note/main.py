"""End-to-end pipeline entrypoint: fetch -> store -> payload -> narrative -> guard -> publish.

run() takes note_date as an explicit parameter rather than reading the system
clock -- the same discipline metrics.py and payload.py already enforce,
applied one layer up. The only deliberate clock read in this whole
application lives in the __main__ block below.

Resilience is scoped precisely, per CLAUDE.md Sec.4: a single series' fetch
failure is caught and logged, then the run continues -- build_note_facts
falls back to whatever's already in the store (possibly nothing, possibly a
stale prior value) and marks it accordingly. That is the *only* place this
module catches and continues. Two things are never masked, and always
propagate uncaught so the run fails loudly and publishes nothing:

- NumericFidelityError: a narrated figure didn't trace to the payload.
- NoDataAvailableError: every one of fred/rba/yfinance -- three genuinely
  independent providers -- failed to produce a single observation this run.
  That combination is a much stronger signal of an environment-level problem
  (network/DNS/platform outage) than of three unrelated data sources
  coincidentally having nothing to report on the same day, so it is treated
  as a structural failure, not a per-series data gap: publishing a
  content-free page in that case would hurt trust in the archive rather than
  preserve it, and NoteFacts's own sections field (min_length=1) is not
  softened to allow it. This check runs before build_note_facts is ever
  called, so that invariant is never at risk of tripping unexpectedly.
"""

import logging
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path

from apps.macro_note.guards import NumericFidelityError, check_numeric_fidelity
from apps.macro_note.models import SeriesSource
from apps.macro_note.narrative import NarrativeGenerator
from apps.macro_note.payload import build_note_facts
from apps.macro_note.publish import DEFAULT_DOCS_DIR, publish_note
from apps.macro_note.registry import SERIES_REGISTRY
from apps.macro_note.sources.base import SourceProvider
from apps.macro_note.sources.fred import FredSource
from apps.macro_note.sources.market import MarketSource
from apps.macro_note.sources.rba import RbaSource
from apps.macro_note.store import DEFAULT_DATA_DIR, ObservationStore

logger = logging.getLogger(__name__)

# Comfortably wider than metrics.HISTORY_LOOKBACK's 45 observations, with buffer for
# weekend/holiday gaps. Connectors return full historical windows for whatever range
# is requested, not just the latest point, so refetching this whole window every run
# is deliberately self-healing: a run that was skipped or failed for several days is
# automatically backfilled by the next successful one, at no extra cost beyond the
# idempotent upsert already doing the deduplication.
FETCH_LOOKBACK_DAYS = 60


class NoDataAvailableError(RuntimeError):
    """Raised when every data source failed to produce a single observation this run."""


def run(
    note_date: date,
    data_dir: Path = DEFAULT_DATA_DIR,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    sources: Mapping[SeriesSource, SourceProvider] | None = None,
    narrative_generator: NarrativeGenerator | None = None,
    overwrite: bool = False,
) -> Path:
    """Run the full pipeline for `note_date` and return the path to the published note."""
    sources = sources or _default_sources()
    narrative_generator = narrative_generator or NarrativeGenerator()

    store = ObservationStore(data_dir)
    try:
        fetched_anything = _fetch_and_store(store, sources, note_date)
        if not any(fetched_anything.values()):
            raise NoDataAvailableError(
                "No observations were fetched from any source this run "
                f"({fetched_anything}). All three independent providers failing "
                "simultaneously indicates an environment-level problem, not a "
                "routine per-series gap -- refusing to publish rather than mask it."
            )
        facts = build_note_facts(store, note_date)
    finally:
        store.close()

    narrative = narrative_generator.generate(facts)
    try:
        check_numeric_fidelity(narrative, facts)
    except NumericFidelityError:
        logger.error(
            "Numeric fidelity guard blocked publication.\nNarrative:\n%s\nNoteFacts payload:\n%s",
            narrative.model_dump_json(indent=2),
            facts.model_dump_json(indent=2),
        )
        raise
    return publish_note(facts, narrative, docs_dir, overwrite=overwrite)


def _default_sources() -> dict[SeriesSource, SourceProvider]:
    return {"fred": FredSource(), "rba": RbaSource(), "yfinance": MarketSource()}


def _fetch_and_store(
    store: ObservationStore, sources: Mapping[SeriesSource, SourceProvider], note_date: date
) -> dict[SeriesSource, bool]:
    """Fetch and upsert every registry series. Returns, per source, whether at least
    one observation was successfully fetched this run.

    A single series' failure -- raised (FRED/RBA) or reported as an empty list
    (yfinance never raises, see sources/market.py) -- is logged and skipped, never
    raised further: build_note_facts falls back to whatever the store already has.
    """
    start = note_date - timedelta(days=FETCH_LOOKBACK_DAYS)
    fetched_anything: dict[SeriesSource, bool] = dict.fromkeys(sources, False)
    for series_meta in SERIES_REGISTRY:
        source = sources[series_meta.source]
        try:
            observations = source.fetch_observations(
                series_meta.series_id, series_meta.source_code, start=start, end=note_date
            )
        except Exception:  # deliberately broad: no single connector may abort the run
            logger.exception(
                "Fetch failed for %s (%s); falling back to last stored value.",
                series_meta.series_id,
                series_meta.source,
            )
            continue
        if observations:
            fetched_anything[series_meta.source] = True
        store.upsert(observations, source=series_meta.source)
    return fetched_anything


if __name__ == "__main__":
    _note_date = date.today()
    try:
        _path = run(_note_date)
    except (NumericFidelityError, NoDataAvailableError) as exc:
        print(f"::error::{exc}")
        raise
    print(f"Published {_path}")
