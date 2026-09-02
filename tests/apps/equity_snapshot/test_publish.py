"""Publish-layer tests for the equity snapshot pages.

Real BHP.AX / JPM / AAPL fundamentals from test_calculations.py, run through
build_equity_snapshot, then written to a tmp docs tree. These assert the two
deliberate departures from apps/macro_note and apps/comps documented in
publish.py: write_snapshot overwrites by default (a snapshot is a live view
that is meant to be replaced, not a permanent dated record), and the index is
a flat list of the fixed ticker set ordered alphabetically by ticker (a
near-simultaneous refresh makes freshness-based ordering pure noise).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import build_equity_snapshot
from apps.equity_snapshot.publish import publish_snapshot, update_index, write_snapshot
from apps.equity_snapshot.render import render_snapshot
from tests.apps.equity_snapshot.test_calculations import _AAPL, _BHP, _JPM

_BHP_SNAPSHOT = build_equity_snapshot(_BHP)
_JPM_SNAPSHOT = build_equity_snapshot(_JPM)
_AAPL_SNAPSHOT = build_equity_snapshot(_AAPL)

_NARRATIVE = TickerNarrative(
    headline="A concise valuation and profitability readout",
    summary="The company trades on the multiples and margins tabulated below.",
)

_INDEX_TEMPLATE = """# Equity Snapshots

Point-in-time valuation and profitability snapshots for a fixed watchlist of
tickers. Each page is refreshed in place as prices move.

<!-- equities:start -->
<!-- equities:end -->
"""


@pytest.fixture
def equity_dir(tmp_path: Path) -> Iterator[Path]:
    equity_dir = tmp_path / "equities"
    equity_dir.mkdir()
    (equity_dir / "index.md").write_text(_INDEX_TEMPLATE)
    yield equity_dir


# --- write_snapshot ---


def test_write_snapshot_writes_rendered_content_to_slug_path(equity_dir: Path) -> None:
    path = write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    assert path == equity_dir / "bhp-ax.md"
    assert path.read_text() == render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)


def test_write_snapshot_overwrites_by_default(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    refreshed = TickerNarrative(
        headline="A concise valuation and profitability readout",
        summary="An updated readout after the latest quote.",
    )
    path = write_snapshot(_BHP_SNAPSHOT, refreshed, equity_dir)

    assert path.read_text() == render_snapshot(_BHP_SNAPSHOT, refreshed)
    assert "An updated readout after the latest quote." in path.read_text()


def test_write_snapshot_overwrite_false_raises_when_file_exists(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    with pytest.raises(FileExistsError):
        write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir, overwrite=False)


def test_write_snapshot_creates_equity_dir_if_missing(tmp_path: Path) -> None:
    equity_dir = tmp_path / "equities"

    path = write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    assert path.exists()
    assert path.read_text() == render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)


# --- update_index ---


def test_update_index_raises_when_markers_missing(tmp_path: Path) -> None:
    equity_dir = tmp_path / "equities"
    equity_dir.mkdir()
    (equity_dir / "index.md").write_text("# Equity Snapshots\n\nNo markers here.\n")

    with pytest.raises(ValueError, match="equities:start"):
        update_index(equity_dir)


def test_update_index_writes_row_with_company_ticker_link_and_as_of(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    update_index(equity_dir)

    index_text = (equity_dir / "index.md").read_text()
    assert "- [BHP Group Limited (BHP.AX)](bhp-ax.md) — snapshot as of 2026-08-24" in index_text


def test_update_index_sorts_rows_alphabetically_by_ticker(equity_dir: Path) -> None:
    for snapshot in (_JPM_SNAPSHOT, _BHP_SNAPSHOT, _AAPL_SNAPSHOT):
        write_snapshot(snapshot, _NARRATIVE, equity_dir)

    update_index(equity_dir)

    index_text = (equity_dir / "index.md").read_text()
    aapl_pos = index_text.index("(AAPL)")
    bhp_pos = index_text.index("(BHP.AX)")
    jpm_pos = index_text.index("(JPM)")
    assert aapl_pos < bhp_pos < jpm_pos


def test_update_index_preserves_hand_authored_prose_around_markers(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    update_index(equity_dir)

    index_text = (equity_dir / "index.md").read_text()
    assert index_text.startswith("# Equity Snapshots\n")
    assert "Each page is refreshed in place as prices move." in index_text


def test_update_index_is_idempotent(equity_dir: Path) -> None:
    for snapshot in (_BHP_SNAPSHOT, _JPM_SNAPSHOT):
        write_snapshot(snapshot, _NARRATIVE, equity_dir)

    update_index(equity_dir)
    first = (equity_dir / "index.md").read_text()
    update_index(equity_dir)
    second = (equity_dir / "index.md").read_text()

    assert first == second


def test_update_index_reflects_a_hand_deleted_file(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)
    write_snapshot(_JPM_SNAPSHOT, _NARRATIVE, equity_dir)
    update_index(equity_dir)

    (equity_dir / "jpm.md").unlink()
    update_index(equity_dir)

    index_text = (equity_dir / "index.md").read_text()
    assert "(BHP.AX)" in index_text
    assert "jpm.md" not in index_text


def test_update_index_omits_model_authored_headline(equity_dir: Path) -> None:
    write_snapshot(_BHP_SNAPSHOT, _NARRATIVE, equity_dir)

    update_index(equity_dir)

    index_text = (equity_dir / "index.md").read_text()
    assert _NARRATIVE.headline not in index_text


# --- publish_snapshot ---


def test_publish_snapshot_writes_file_and_updates_index(equity_dir: Path) -> None:
    docs_dir = equity_dir.parent

    path = publish_snapshot(_BHP_SNAPSHOT, _NARRATIVE, docs_dir=docs_dir)

    assert path == docs_dir / "equities" / "bhp-ax.md"
    assert path.exists()
    index_text = (docs_dir / "equities" / "index.md").read_text()
    assert "- [BHP Group Limited (BHP.AX)](bhp-ax.md) — snapshot as of 2026-08-24" in index_text


def test_publish_snapshot_reruns_are_idempotent(equity_dir: Path) -> None:
    docs_dir = equity_dir.parent

    publish_snapshot(_BHP_SNAPSHOT, _NARRATIVE, docs_dir=docs_dir)
    publish_snapshot(_BHP_SNAPSHOT, _NARRATIVE, docs_dir=docs_dir)

    index_text = (docs_dir / "equities" / "index.md").read_text()
    assert index_text.count("bhp-ax.md") == 1
