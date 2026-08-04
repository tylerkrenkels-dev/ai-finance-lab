import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from apps.macro_note.guards import NumericFidelityError
from apps.macro_note.main import NoDataAvailableError, run
from apps.macro_note.models import NoteFacts, NoteNarrative, Observation, SeriesSource
from apps.macro_note.narrative import NarrativeGenerator
from apps.macro_note.sources.base import SourceProvider

NOTE_DATE = date(2026, 7, 31)

_INDEX_TEMPLATE = """# Daily Notes

The Macro Research Digest publishes here every weekday morning once Phase 1
is live. Each note is dated and permanent.

<!-- notes:start -->
<!-- notes:end -->
"""


def _seed_docs_dir(tmp_path: Path) -> Path:
    """publish_note requires docs/notes/index.md to already exist with the marker
    pair -- it deliberately never auto-creates a hand-authored docs page."""
    docs_dir = tmp_path / "docs"
    notes_dir = docs_dir / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "index.md").write_text(_INDEX_TEMPLATE)
    return docs_dir


class _StubGenerator(NarrativeGenerator):
    """A NarrativeGenerator that returns a fixed narrative without calling the API."""

    def __init__(self, narrative: NoteNarrative) -> None:
        self._narrative = narrative

    def generate(self, facts: NoteFacts) -> NoteNarrative:  # type: ignore[override]
        return self._narrative


class _AlwaysFailsSource:
    """Simulates FRED/RBA's failure mode: raises for every call."""

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        raise RuntimeError(f"simulated outage fetching {series_id}")


class _AlwaysEmptySource:
    """Simulates yfinance's failure mode: never raises, always returns nothing."""

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        return []


class _ThinFakeSource:
    """A healthy source with only two calendar days of history -- a cold cache where
    the source itself works fine but there's no deep history yet for 1W/1M changes."""

    def __init__(self, value: float) -> None:
        self._value = value

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        fetched_at = datetime.now(UTC)
        return [
            Observation(series_id=series_id, value=self._value, as_of=end, fetched_at=fetched_at),
            Observation(
                series_id=series_id,
                value=self._value,
                as_of=end - timedelta(days=1),
                fetched_at=fetched_at,
            ),
        ]


class _PartiallyFailingFredSource:
    """FRED-shaped source: fails for one specific series, succeeds for the rest."""

    def __init__(self, failing_series_id: str, value: float) -> None:
        self._failing_series_id = failing_series_id
        self._value = value

    def fetch_observations(
        self, series_id: str, source_code: str, start: date, end: date
    ) -> list[Observation]:
        if series_id == self._failing_series_id:
            raise RuntimeError(f"simulated outage fetching {series_id}")
        return [
            Observation(
                series_id=series_id, value=self._value, as_of=end, fetched_at=datetime.now(UTC)
            )
        ]


def _fixed_narrative() -> NoteNarrative:
    return NoteNarrative(
        headline="Markets Steady",
        summary="No material moves today.",
        bullets=["No material moves today."],
    )


def _healthy_sources(value: float = 100.0) -> dict[SeriesSource, SourceProvider]:
    return {
        "fred": _ThinFakeSource(value),
        "rba": _ThinFakeSource(value),
        "yfinance": _ThinFakeSource(value),
    }


def test_run_tolerates_one_source_failing_and_still_publishes(tmp_path: Path) -> None:
    sources: dict[SeriesSource, SourceProvider] = {
        "fred": _PartiallyFailingFredSource(failing_series_id="us_10y", value=4.25),
        "rba": _ThinFakeSource(3.85),
        "yfinance": _ThinFakeSource(1950.0),
    }

    path = run(
        NOTE_DATE,
        data_dir=tmp_path / "data",
        docs_dir=_seed_docs_dir(tmp_path),
        sources=sources,
        narrative_generator=_StubGenerator(_fixed_narrative()),
    )

    assert path.exists()
    rendered = path.read_text()
    # RBA's metric is present despite fred's failure -- the one failure didn't abort
    # the run or drop the other, healthy sources' data.
    assert "RBA Cash Rate" in rendered
    # The failed series is reported, not silently dropped.
    assert "No data available for US 10-Year Treasury Yield." in rendered


def test_run_completes_on_cold_cache_when_sources_succeed(tmp_path: Path) -> None:
    """First-ever run / cache eviction: store starts empty, but all sources are
    healthy. Should complete and publish a real note -- not raise, not degrade
    the way a total-outage does."""
    path = run(
        NOTE_DATE,
        data_dir=tmp_path / "data",
        docs_dir=_seed_docs_dir(tmp_path),
        sources=_healthy_sources(4.25),
        narrative_generator=_StubGenerator(_fixed_narrative()),
    )

    assert path.exists()
    rendered = path.read_text()
    # Real, current values are present...
    assert "4.25" in rendered
    # ...but only two days of history exist, so 1W/1M changes can't be computed --
    # the metrics table shows the "no data for this horizon" placeholder, not a
    # fabricated one.
    assert rendered.count("—") >= 2


def test_run_raises_when_all_three_sources_fail_simultaneously(tmp_path: Path) -> None:
    """Total, simultaneous failure of all three independent sources is treated as
    an environment-level problem, not a routine per-series gap: raise loudly,
    before ever reaching build_note_facts, and publish nothing."""
    sources: dict[SeriesSource, SourceProvider] = {
        "fred": _AlwaysFailsSource(),
        "rba": _AlwaysFailsSource(),
        "yfinance": _AlwaysEmptySource(),  # yfinance's real failure mode never raises
    }
    docs_dir = tmp_path / "docs"

    with pytest.raises(NoDataAvailableError):
        run(
            NOTE_DATE,
            data_dir=tmp_path / "data",
            docs_dir=docs_dir,
            sources=sources,
            narrative_generator=_StubGenerator(_fixed_narrative()),
        )

    assert not (docs_dir / "notes" / f"{NOTE_DATE.isoformat()}.md").exists()


def test_run_propagates_numeric_fidelity_failure_and_publishes_nothing(tmp_path: Path) -> None:
    fabricated = NoteNarrative(
        headline="Yields Surge",
        summary="Yields jumped 9999 basis points today.",
        bullets=["A 9999 basis point move, unlike anything on record."],
    )
    docs_dir = tmp_path / "docs"

    with pytest.raises(NumericFidelityError):
        run(
            NOTE_DATE,
            data_dir=tmp_path / "data",
            docs_dir=docs_dir,
            sources=_healthy_sources(4.25),
            narrative_generator=_StubGenerator(fabricated),
        )

    assert not (docs_dir / "notes" / f"{NOTE_DATE.isoformat()}.md").exists()


def test_run_logs_full_narrative_and_payload_on_guard_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """#42: a guard failure must leave the real narrative text and the NoteFacts
    payload it was checked against in the log -- not just the guard's own terse
    exception message -- since publish_note is never reached to persist either
    one anywhere else."""
    fabricated = NoteNarrative(
        headline="Yields Surge",
        summary="Yields jumped 9999 basis points today, a record move.",
        bullets=["A 9999 basis point move, unlike anything on record."],
    )
    docs_dir = tmp_path / "docs"

    with (
        caplog.at_level(logging.ERROR, logger="apps.macro_note.main"),
        pytest.raises(NumericFidelityError),
    ):
        run(
            NOTE_DATE,
            data_dir=tmp_path / "data",
            docs_dir=docs_dir,
            sources=_healthy_sources(4.25),
            narrative_generator=_StubGenerator(fabricated),
        )

    assert len(caplog.records) == 1
    logged = caplog.records[0].getMessage()
    # The full narrative text survives in the log, not just the flagged fragment --
    # every field, including ones that had nothing wrong with them.
    assert fabricated.headline in logged
    assert fabricated.summary in logged
    assert fabricated.bullets[0] in logged
    # The NoteFacts payload the narrative was checked against is present too, e.g.
    # a real computed metric value that made it into the sourced note.
    assert "4.25" in logged
    assert str(NOTE_DATE) in logged
