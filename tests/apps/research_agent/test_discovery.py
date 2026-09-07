"""Tests for list_available_sources against fixture pages."""

from datetime import date
from pathlib import Path

import pytest

from apps.research_agent.discovery import list_available_sources
from apps.research_agent.sources import (
    read_comp_table,
    read_equity_snapshot,
    read_macro_note,
)

_FIXTURES = Path(__file__).parent / "fixtures"


class TestListAvailableSources:
    def test_lists_all_three_systems_from_fixtures(self) -> None:
        refs = list_available_sources(docs_dir=_FIXTURES)
        assert {r.system for r in refs} == {"macro_note", "comps", "equity_snapshot"}

        macro = [r for r in refs if r.system == "macro_note"]
        assert [r.key for r in macro] == ["2026-09-01", "2026-08-28"]  # newest first
        assert macro[0].doc_id == "macro_note/2026-09-01"
        assert macro[0].as_of == date(2026, 9, 1)
        assert "Rates Hold Steady" in macro[0].label

        equity = [r for r in refs if r.system == "equity_snapshot"]
        assert [r.key for r in equity] == ["AAPL", "BHP.AX", "CBA.AX", "JPM", "MSFT"]
        assert equity[0].label == "Apple Inc. (AAPL)"

        comps = [r for r in refs if r.system == "comps"]
        assert {r.key for r in comps} == {
            "splunk-cisco-qatalyst",
            "footlocker-dicks-evercore",
            "norfolk-southern-union-pacific-wells-fargo",
        }
        # newest filing first
        assert comps[0].key == "norfolk-southern-union-pacific-wells-fargo"

    def test_comps_without_a_published_page_are_not_listed(self) -> None:
        keys = {r.key for r in list_available_sources(docs_dir=_FIXTURES)}
        assert "chart-bakerhughes-wellsfargo" not in keys  # real registry entry, no fixture .md

    def test_every_listed_ref_reads_back_to_its_doc_id(self) -> None:
        for ref in list_available_sources(docs_dir=_FIXTURES):
            if ref.system == "macro_note":
                page = read_macro_note(date.fromisoformat(ref.key), docs_dir=_FIXTURES)
            elif ref.system == "equity_snapshot":
                page = read_equity_snapshot(ref.key, docs_dir=_FIXTURES)
            else:
                page = read_comp_table(ref.key, docs_dir=_FIXTURES)
            assert page is not None and page.doc_id == ref.doc_id


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
