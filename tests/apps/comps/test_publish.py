from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.comps.models import ComparableTransactionsTable, Deal
from apps.comps.publish import publish_table, update_index, write_table
from apps.comps.registry import DEALS, TABLES
from apps.comps.render import render_table

_DEAL_BY_ID = {d.deal_id: d for d in DEALS}

_INDEX_TEMPLATE = """# Deal Comps

Hand-curated M&A comparable-transactions tables, transcribed once from real
DEFM14A filings on SEC EDGAR, with every figure traceable to a cited source.

<!-- comps:start -->
<!-- comps:end -->
"""


def _table(table_id: str) -> ComparableTransactionsTable:
    return next(t for t in TABLES if t.table_id == table_id)


def _deal_for(table_id: str) -> Deal:
    return _DEAL_BY_ID[_table(table_id).deal_id]


@pytest.fixture
def comps_dir(tmp_path: Path) -> Iterator[Path]:
    comps_dir = tmp_path / "comps"
    comps_dir.mkdir()
    (comps_dir / "index.md").write_text(_INDEX_TEMPLATE)
    yield comps_dir


def test_write_table_writes_rendered_content_to_table_filename(comps_dir: Path) -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    path = write_table(table, deal, comps_dir)

    assert path == comps_dir / "splunk-cisco-qatalyst.md"
    assert path.read_text() == render_table(table, deal)


def test_write_table_refuses_to_overwrite_by_default(comps_dir: Path) -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")
    write_table(table, deal, comps_dir)

    with pytest.raises(FileExistsError):
        write_table(table, deal, comps_dir)


def test_write_table_overwrite_true_replaces_existing_file(comps_dir: Path) -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")
    write_table(table, deal, comps_dir)

    path = write_table(table, deal, comps_dir, overwrite=True)

    assert path.read_text() == render_table(table, deal)


def test_update_index_raises_when_markers_missing(tmp_path: Path) -> None:
    comps_dir = tmp_path / "comps"
    comps_dir.mkdir()
    (comps_dir / "index.md").write_text("# Deal Comps\n\nNo markers here.\n")

    with pytest.raises(ValueError, match="comps:start"):
        update_index(comps_dir)


def test_publish_table_writes_file_and_updates_index(comps_dir: Path) -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")
    docs_dir = comps_dir.parent

    path = publish_table(table, deal, docs_dir=docs_dir)

    assert path == docs_dir / "comps" / "splunk-cisco-qatalyst.md"
    assert path.exists()

    index_text = (docs_dir / "comps" / "index.md").read_text()
    assert (
        "- [Qatalyst Partners — Selected Transactions Analysis](splunk-cisco-qatalyst.md)"
        in index_text
    )
    # Hand-authored prose above the markers must survive untouched.
    assert "every figure traceable to a cited source" in index_text


def test_publish_table_reruns_are_idempotent_with_overwrite(comps_dir: Path) -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")
    docs_dir = comps_dir.parent

    publish_table(table, deal, docs_dir=docs_dir, overwrite=True)
    publish_table(table, deal, docs_dir=docs_dir, overwrite=True)

    index_text = (docs_dir / "comps" / "index.md").read_text()
    assert index_text.count("splunk-cisco-qatalyst.md") == 1


def test_update_index_groups_norfolk_southern_tables_under_one_deal_heading(
    comps_dir: Path,
) -> None:
    docs_dir = comps_dir.parent
    for table_id in (
        "norfolk-southern-union-pacific-wells-fargo",
        "norfolk-southern-union-pacific-bofa",
    ):
        publish_table(_table(table_id), _deal_for(table_id), docs_dir=docs_dir)

    index_text = (docs_dir / "comps" / "index.md").read_text()

    assert index_text.count("Norfolk Southern Corporation / Union Pacific Corporation") == 1
    assert (
        "- [BofA Securities, Inc. — Selected Precedent Transactions Analysis]"
        "(norfolk-southern-union-pacific-bofa.md)" in index_text
    )
    assert (
        "- [Wells Fargo Securities, LLC — Selected Transactions Analysis]"
        "(norfolk-southern-union-pacific-wells-fargo.md)" in index_text
    )
    # Alphabetical-by-advisor tiebreak: BofA before Wells Fargo.
    assert index_text.index("BofA Securities") < index_text.index("Wells Fargo Securities")


def test_update_index_marks_pending_deal_with_bold_marker(comps_dir: Path) -> None:
    docs_dir = comps_dir.parent
    publish_table(
        _table("norfolk-southern-union-pacific-wells-fargo"),
        _deal_for("norfolk-southern-union-pacific-wells-fargo"),
        docs_dir=docs_dir,
    )

    index_text = (docs_dir / "comps" / "index.md").read_text()

    assert (
        "### Norfolk Southern Corporation / Union Pacific Corporation — **Pending**" in index_text
    )


def test_update_index_orders_deal_groups_by_most_recent_filing_date_descending(
    comps_dir: Path,
) -> None:
    docs_dir = comps_dir.parent
    # Splunk/Cisco filed 2023-10-30; Chart/Baker Hughes filed 2025-09-08;
    # Norfolk Southern filed 2025-10-01 -- most recent first.
    for table_id in (
        "splunk-cisco-qatalyst",
        "chart-bakerhughes-wellsfargo",
        "norfolk-southern-union-pacific-wells-fargo",
    ):
        publish_table(_table(table_id), _deal_for(table_id), docs_dir=docs_dir)

    index_text = (docs_dir / "comps" / "index.md").read_text()

    norfolk_pos = index_text.index("Norfolk Southern Corporation / Union Pacific Corporation")
    chart_pos = index_text.index("Chart Industries, Inc. / Baker Hughes Company")
    splunk_pos = index_text.index("Splunk, Inc. / Cisco Systems, Inc.")
    assert norfolk_pos < chart_pos < splunk_pos
