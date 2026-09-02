"""End-to-end pipeline entrypoint: fetch -> payload -> narrative -> guard -> publish, per ticker.

Mirrors apps/macro_note/main.py's shape and its explicit-inputs discipline --
run() takes the ticker list as a parameter (this system has no clock to read)
and the fetch callable and narrative generator are injectable seams -- but the
resilience shape is different, because this system publishes one standalone
page PER TICKER, not one combined note.

Per-ticker isolation. A single ticker's failure at any of three stages is
caught, logged, recorded on the returned RunResult, and the loop moves to the
next ticker:

- fetch returned None: fetch_fundamentals already retried with backoff and
  gave up (see sources.py). There is no store in this app -- the previously
  published docs/equities/<ticker>.md IS the fallback -- so run() simply does
  not touch that file. Its last-published content and as-of date stay on the
  site; update_index (run by every healthy ticker) keeps its row, now with a
  visibly older date beside the fresh ones. A ticker with no prior page is
  just absent this run and picked up by the next successful one.
- NarrativeParseError: the model's response didn't validate into
  TickerNarrative. Logged here with the raw model text (otherwise
  unrecoverable -- see narrative.py) and the EquitySnapshot payload.
- NumericFidelityError: a narrated numeral didn't trace to the payload. This
  does NOT weaken CLAUDE.md Sec.2. "The run fails and publishes nothing" is
  upheld per ticker: the offending ticker is not published; its existing page
  -- itself a previously guard-passed artifact -- stays. macro_note aborts the
  whole run here only because it has a single combined artifact with nothing
  to salvage.

Two failures are NOT isolated:

- AllTickersFailedError: every ticker failed and nothing was published. With a
  single provider (yfinance), that is a much stronger signal of a network or
  platform outage than of five companies independently having no data -- the
  same reasoning macro_note applies to all-three-providers-empty. Raised after
  the loop; publishes nothing.
- build_equity_snapshot raising: that is pure calculation over an
  already-validated RawFundamentals. A raise there is a calculations.py bug,
  not a data condition, and must fail the whole run loudly -- it is never
  caught here, exactly as macro_note lets build_note_facts failures propagate.

Partial failure (some published, some failed) is a real outcome an
all-or-nothing Path return cannot express, so run() returns a RunResult. The
successful pages are published before run() returns; __main__ then exits
non-zero so a partial run shows red in CI while the site stays current. A
permanently delisted ticker therefore reddens every run until it is removed
from WATCHLIST -- which is the correct prompt to fix the config.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from apps.equity_snapshot.guards import NumericFidelityError, check_numeric_fidelity
from apps.equity_snapshot.narrative import NarrativeGenerator, NarrativeParseError
from apps.equity_snapshot.payload import build_equity_snapshot
from apps.equity_snapshot.publish import DEFAULT_DOCS_DIR, publish_snapshot
from apps.equity_snapshot.sources import RawFundamentals, fetch_fundamentals

logger = logging.getLogger(__name__)

# The fixed watchlist: the exact five tickers investigated empirically when
# sources.py and calculations.py were written, and fixture-tested throughout.
# Two ASX mega-caps (BHP.AX exercises the trading-vs-reporting currency gate;
# CBA.AX the bank sector-suppression path without a currency gate) plus three
# US names for context (AAPL/MSFT the every-field-present path, JPM the US-bank
# suppression path). AU-focused, US context -- the original spec's positioning.
WATCHLIST: tuple[str, ...] = ("AAPL", "MSFT", "JPM", "BHP.AX", "CBA.AX")

FailureStage = Literal["fetch", "narrative", "guard"]


@dataclass(frozen=True)
class TickerFailure:
    """One ticker that did not publish this run, and the stage it failed at."""

    ticker: str
    stage: FailureStage
    detail: str


@dataclass(frozen=True)
class RunResult:
    """Outcome of a run: the pages actually published, and the tickers that failed."""

    published: list[Path] = field(default_factory=list)
    failures: list[TickerFailure] = field(default_factory=list)


class AllTickersFailedError(RuntimeError):
    """Raised when every ticker failed this run and nothing was published."""


def run(
    tickers: Sequence[str] = WATCHLIST,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    fetch: Callable[[str], RawFundamentals | None] = fetch_fundamentals,
    narrative_generator: NarrativeGenerator | None = None,
    overwrite: bool = True,
) -> RunResult:
    """Run the full pipeline for every ticker in `tickers`.

    Each ticker succeeds or fails independently. Returns a RunResult listing the
    published pages and the per-ticker failures. Raises AllTickersFailedError if
    nothing published at all.
    """
    narrative_generator = narrative_generator or NarrativeGenerator()

    result = RunResult()
    for ticker in tickers:
        outcome = _run_one(ticker, docs_dir, fetch, narrative_generator, overwrite=overwrite)
        if isinstance(outcome, Path):
            result.published.append(outcome)
        else:
            result.failures.append(outcome)

    if result.failures and not result.published:
        raise AllTickersFailedError(
            f"Every ticker failed this run ({[f.ticker for f in result.failures]}); "
            "with a single data provider this indicates an environment-level "
            "problem, not independent per-ticker data gaps -- publishing nothing."
        )

    if result.failures:
        logger.error(
            "Published %d/%d snapshots; failed: %s",
            len(result.published),
            len(tickers),
            [(f.ticker, f.stage) for f in result.failures],
        )
    return result


def _run_one(
    ticker: str,
    docs_dir: Path,
    fetch: Callable[[str], RawFundamentals | None],
    narrative_generator: NarrativeGenerator,
    *,
    overwrite: bool,
) -> Path | TickerFailure:
    """Run the pipeline for one ticker. Returns the published Path or a TickerFailure.

    build_equity_snapshot is deliberately outside every try: a raise there is a
    calculations.py defect, not a per-ticker data condition, and must propagate.
    """
    fundamentals = fetch(ticker)
    if fundamentals is None:
        logger.error(
            "Fundamentals unavailable for %s; skipping -- its existing page, if any, "
            "stays as last published.",
            ticker,
        )
        return TickerFailure(ticker=ticker, stage="fetch", detail="fundamentals unavailable")

    snapshot = build_equity_snapshot(fundamentals)

    try:
        narrative = narrative_generator.generate(snapshot)
    except NarrativeParseError as exc:
        logger.error(
            "Narrative generation failed to parse for %s.\nRaw model output:\n%s\n"
            "EquitySnapshot payload:\n%s",
            ticker,
            exc.raw_text,
            snapshot.model_dump_json(indent=2),
        )
        return TickerFailure(ticker=ticker, stage="narrative", detail=str(exc))

    try:
        check_numeric_fidelity(narrative, snapshot)
    except NumericFidelityError as exc:
        logger.error(
            "Numeric fidelity guard blocked %s.\nNarrative:\n%s\nEquitySnapshot payload:\n%s\n%s",
            ticker,
            narrative.model_dump_json(indent=2),
            snapshot.model_dump_json(indent=2),
            exc,
        )
        return TickerFailure(
            ticker=ticker, stage="guard", detail="untraceable numeral in narrative"
        )

    return publish_snapshot(snapshot, narrative, docs_dir, overwrite=overwrite)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        _result = run()
    except AllTickersFailedError as exc:
        print(f"::error::{exc}")
        raise
    for _failure in _result.failures:
        print(f"::warning::{_failure.ticker}: {_failure.stage} -- {_failure.detail}")
    for _path in _result.published:
        print(f"Published {_path}")
    if _result.failures:
        print(
            f"::error::published {len(_result.published)}/{len(WATCHLIST)}; "
            f"{len(_result.failures)} ticker(s) failed"
        )
        raise SystemExit(1)
