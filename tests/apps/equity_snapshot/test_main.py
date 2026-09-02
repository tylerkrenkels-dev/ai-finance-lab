"""Orchestrator tests for the equity snapshot pipeline.

run() fans the pipeline out over a fixed watchlist, one standalone page per
ticker. Unlike apps/macro_note's run(), a fetch / narrative-parse / guard
failure on one ticker is isolated -- logged, recorded on the RunResult, and
the loop moves on -- because the other tickers' pages are independent
artifacts. The two things that are NOT isolated: every ticker failing (an
environment-level signal -> AllTickersFailedError), and a real calculations.py
bug (a code defect, not a data condition -> propagates uncaught).

Fakes here inject a `fetch` callable (ticker -> RawFundamentals | None) and a
NarrativeGenerator subclass, the same seams macro_note's test_main uses. The
four real investigated fixtures are reused from test_calculations; _MSFT is
built here since calculations has no MSFT test of its own.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.equity_snapshot.main import (
    WATCHLIST,
    AllTickersFailedError,
    RunResult,
    TickerFailure,
    run,
)
from apps.equity_snapshot.narrative import NarrativeGenerator, NarrativeParseError, TickerNarrative
from apps.equity_snapshot.payload import build_equity_snapshot
from apps.equity_snapshot.render import render_snapshot
from apps.equity_snapshot.sources import RawFundamentals
from tests.apps.equity_snapshot.test_calculations import _AAPL, _BHP, _CBA, _JPM

_MSFT = RawFundamentals(
    ticker="MSFT",
    quote_type="EQUITY",
    company_name="Microsoft Corporation",
    sector="Technology",
    currency="USD",
    financial_currency="USD",
    market_cap=3_800_000_000_000,
    enterprise_value=3_820_000_000_000,
    trailing_pe=38.5,
    forward_pe=33.1,
    price_to_book=14.2,
    price_to_sales_ttm=13.1,
    enterprise_to_ebitda=25.4,
    enterprise_to_revenue=13.0,
    trailing_eps=13.1,
    forward_eps=15.2,
    total_revenue=290_000_000_000,
    ebitda=150_000_000_000,
    gross_margins=0.69,
    operating_margins=0.45,
    profit_margins=0.36,
    return_on_equity=0.35,
    return_on_assets=0.19,
    debt_to_equity=32.1,
    current_ratio=1.3,
    quick_ratio=1.2,
    dividend_yield=0.72,
    beta=0.9,
    current_price=505.0,
    previous_close=502.1,
    fifty_two_week_high=520.0,
    fifty_two_week_low=390.0,
    free_cashflow=60_000_000_000,
    operating_cashflow=120_000_000_000,
    shares_outstanding=7_430_000_000,
    quote_as_of=datetime(2026, 8, 24, 20, 0, tzinfo=UTC),
    fetched_at=datetime(2026, 8, 24, 20, 5, tzinfo=UTC),
)

_RAW_BY_TICKER: dict[str, RawFundamentals] = {
    "AAPL": _AAPL,
    "MSFT": _MSFT,
    "JPM": _JPM,
    "BHP.AX": _BHP,
    "CBA.AX": _CBA,
}

_CLEAN_NARRATIVE = TickerNarrative(
    headline="Valuation and profitability readout",
    summary="The multiples and margins are tabulated below.",
)

_INDEX_TEMPLATE = """# Equity Snapshots

Point-in-time valuation and profitability snapshots for a fixed watchlist of
tickers. Each page is refreshed in place as prices move.

<!-- equities:start -->
<!-- equities:end -->
"""


def _seed_docs_dir(tmp_path: Path) -> Path:
    docs_dir = tmp_path / "docs"
    (docs_dir / "equities").mkdir(parents=True)
    (docs_dir / "equities" / "index.md").write_text(_INDEX_TEMPLATE)
    return docs_dir


def _fetch_all(ticker: str) -> RawFundamentals | None:
    return _RAW_BY_TICKER.get(ticker)


def _fetch_none_for(*missing: str):
    def fetch(ticker: str) -> RawFundamentals | None:
        if ticker in missing:
            return None
        return _RAW_BY_TICKER.get(ticker)

    return fetch


class _StubGenerator(NarrativeGenerator):
    """Returns _CLEAN_NARRATIVE for every ticker, unless `per_ticker` overrides it.

    A per_ticker value that is an Exception instance is raised instead of
    returned, so a real NarrativeParseError path can be simulated without the API.
    """

    def __init__(self, per_ticker: dict[str, TickerNarrative | Exception] | None = None) -> None:
        self._per_ticker = per_ticker or {}

    def generate(self, snapshot) -> TickerNarrative:  # type: ignore[override]
        result = self._per_ticker.get(snapshot.ticker, _CLEAN_NARRATIVE)
        if isinstance(result, Exception):
            raise result
        return result


def _index_text(docs_dir: Path) -> str:
    return (docs_dir / "equities" / "index.md").read_text()


# --- watchlist ---


def test_watchlist_is_the_five_investigated_tickers() -> None:
    assert WATCHLIST == ("AAPL", "MSFT", "JPM", "BHP.AX", "CBA.AX")


# --- happy path ---


def test_run_publishes_every_ticker_on_the_happy_path(tmp_path: Path) -> None:
    docs_dir = _seed_docs_dir(tmp_path)

    result = run(docs_dir=docs_dir, fetch=_fetch_all, narrative_generator=_StubGenerator())

    assert isinstance(result, RunResult)
    assert result.failures == []
    assert len(result.published) == 5
    for path in result.published:
        assert path.exists()

    index_text = _index_text(docs_dir)
    assert index_text.count("- [") == 5
    for ticker in ("AAPL", "MSFT", "JPM", "BHP.AX", "CBA.AX"):
        assert f"({ticker})" in index_text


# --- fetch failure isolation ---


def test_run_isolates_a_fetch_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    docs_dir = _seed_docs_dir(tmp_path)

    with caplog.at_level(logging.ERROR):
        result = run(
            docs_dir=docs_dir,
            fetch=_fetch_none_for("AAPL"),
            narrative_generator=_StubGenerator(),
        )

    assert {p.name for p in result.published} == {"msft.md", "jpm.md", "bhp-ax.md", "cba-ax.md"}
    assert result.failures == [
        TickerFailure(ticker="AAPL", stage="fetch", detail="fundamentals unavailable")
    ]
    assert not (docs_dir / "equities" / "aapl.md").exists()
    assert "aapl.md" not in _index_text(docs_dir)
    assert _index_text(docs_dir).count("- [") == 4
    assert any("AAPL" in r.message for r in caplog.records)


def test_run_leaves_a_previously_published_page_untouched_on_fetch_failure(
    tmp_path: Path,
) -> None:
    docs_dir = _seed_docs_dir(tmp_path)
    stale_aapl = _AAPL.model_copy(update={"quote_as_of": datetime(2026, 7, 1, 20, 0, tzinfo=UTC)})
    stale_page = render_snapshot(build_equity_snapshot(stale_aapl), _CLEAN_NARRATIVE)
    (docs_dir / "equities" / "aapl.md").write_text(stale_page)

    result = run(
        docs_dir=docs_dir,
        fetch=_fetch_none_for("AAPL"),
        narrative_generator=_StubGenerator(),
    )

    # The page is the only persistence there is: an un-refreshed ticker keeps its
    # last-published content and as-of date, verbatim.
    assert (docs_dir / "equities" / "aapl.md").read_text() == stale_page
    assert result.failures[0].ticker == "AAPL"
    # ...and update_index (run by the healthy tickers) keeps its row, with the
    # visibly-older date next to the fresh ones.
    index_text = _index_text(docs_dir)
    assert "[Apple Inc. (AAPL)](aapl.md) — snapshot as of 2026-07-01" in index_text
    assert index_text.count("- [") == 5


# --- narrative parse failure isolation ---


def test_run_isolates_a_narrative_parse_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    docs_dir = _seed_docs_dir(tmp_path)
    generator = _StubGenerator(
        {"MSFT": NarrativeParseError("simulated parse failure", raw_text="not json at all")}
    )

    with caplog.at_level(logging.ERROR):
        result = run(docs_dir=docs_dir, fetch=_fetch_all, narrative_generator=generator)

    assert {p.name for p in result.published} == {
        "aapl.md",
        "jpm.md",
        "bhp-ax.md",
        "cba-ax.md",
    }
    assert result.failures == [
        TickerFailure(ticker="MSFT", stage="narrative", detail="simulated parse failure")
    ]
    assert not (docs_dir / "equities" / "msft.md").exists()
    joined = "\n".join(r.message for r in caplog.records)
    assert "not json at all" in joined
    assert "MSFT" in joined


# --- guard failure isolation ---


def test_run_isolates_a_guard_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    docs_dir = _seed_docs_dir(tmp_path)
    fabricated = TickerNarrative(
        headline="Priced for perfection",
        summary="BHP trades at 424242.42x forward earnings, an untraceable figure.",
    )
    generator = _StubGenerator({"BHP.AX": fabricated})

    with caplog.at_level(logging.ERROR):
        result = run(docs_dir=docs_dir, fetch=_fetch_all, narrative_generator=generator)

    assert {p.name for p in result.published} == {
        "aapl.md",
        "msft.md",
        "jpm.md",
        "cba-ax.md",
    }
    assert result.failures == [
        TickerFailure(ticker="BHP.AX", stage="guard", detail="untraceable numeral in narrative")
    ]
    assert not (docs_dir / "equities" / "bhp-ax.md").exists()
    joined = "\n".join(r.message for r in caplog.records)
    assert "BHP.AX" in joined
    assert "424242" in joined


# --- partial failure: RunResult carries both lists ---


def test_run_returns_both_lists_on_partial_failure(tmp_path: Path) -> None:
    docs_dir = _seed_docs_dir(tmp_path)
    generator = _StubGenerator(
        {
            "JPM": TickerNarrative(
                headline="Cheap on every metric",
                summary="Trades at 3.14159x tangible book, a fabricated multiple.",
            )
        }
    )

    result = run(
        docs_dir=docs_dir,
        fetch=_fetch_none_for("AAPL"),
        narrative_generator=generator,
    )

    assert {p.name for p in result.published} == {"msft.md", "bhp-ax.md", "cba-ax.md"}
    assert {(f.ticker, f.stage) for f in result.failures} == {
        ("AAPL", "fetch"),
        ("JPM", "guard"),
    }


# --- structural abort: every ticker failed ---


def test_run_raises_when_every_ticker_fails_to_fetch(tmp_path: Path) -> None:
    docs_dir = _seed_docs_dir(tmp_path)

    with pytest.raises(AllTickersFailedError):
        run(
            docs_dir=docs_dir,
            fetch=lambda _ticker: None,
            narrative_generator=_StubGenerator(),
        )

    # Nothing was published; the index still has empty markers.
    assert _index_text(docs_dir).count("- [") == 0


def test_run_raises_when_every_ticker_fails_across_mixed_stages(tmp_path: Path) -> None:
    docs_dir = _seed_docs_dir(tmp_path)
    bad = TickerNarrative(headline="x", summary="trades at 987654.32x earnings")
    generator = _StubGenerator({t: bad for t in ("MSFT", "JPM", "BHP.AX", "CBA.AX")})

    with pytest.raises(AllTickersFailedError):
        run(
            docs_dir=docs_dir,
            fetch=_fetch_none_for("AAPL"),
            narrative_generator=generator,
        )


# --- a real calculations bug is NOT isolated ---


def test_run_propagates_a_calculations_bug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docs_dir = _seed_docs_dir(tmp_path)

    def boom(_fundamentals: RawFundamentals):
        raise ValueError("simulated calculations defect")

    monkeypatch.setattr("apps.equity_snapshot.main.build_equity_snapshot", boom)

    with pytest.raises(ValueError, match="simulated calculations defect"):
        run(docs_dir=docs_dir, fetch=_fetch_all, narrative_generator=_StubGenerator())
