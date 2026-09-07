"""Tests for the three source-reading tools and the discovery lister.

Two layers, per the design doc:
- fixture tests assert exact SourcePage structure against frozen copies of real
  committed pages;
- drift tests run every reader over the *live* docs/ tree and the registry, so a
  render.py change in any source app fails this suite loudly.
"""

from datetime import date
from pathlib import Path

import pytest

from apps.comps import registry
from apps.research_agent.models import SourcePage
from apps.research_agent.sources import (
    SourcePageIntegrityError,
    read_comp_table,
    read_equity_snapshot,
    read_macro_note,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_BROKEN = _FIXTURES / "broken"
_REPO_DOCS = Path(__file__).resolve().parents[3] / "docs"


def _cells(page: SourcePage) -> list[str]:
    return [v for section in page.sections for row in section.rows for v in row.values()]


# --------------------------------------------------------------------------- macro


class TestReadMacroNote:
    def test_missing_note_returns_none(self) -> None:
        assert read_macro_note(date(2020, 1, 1), docs_dir=_FIXTURES) is None

    def test_envelope_fields(self) -> None:
        page = read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES)
        assert page is not None
        assert page.system == "macro_note"
        assert page.doc_id == "macro_note/2026-09-01"
        assert page.page_path == str(_FIXTURES / "notes" / "2026-09-01.md")
        assert page.subject_terms == []
        assert page.as_of == date(2026, 9, 1)
        assert page.stale is True

    def test_data_warnings_captured_verbatim_and_not_a_section(self) -> None:
        page = read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES)
        assert page is not None
        assert page.data_warnings[0] == (
            "US CPI (Year-over-Year) is stale: last updated 2026-07-01 (62 days ago)."
        )
        assert len(page.data_warnings) == 8
        assert "Data Warnings" not in [s.heading for s in page.sections]

    def test_sections_are_qualified_and_carry_verbatim_figures(self) -> None:
        page = read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES)
        assert page is not None
        by_heading = {s.heading: s for s in page.sections}
        assert set(by_heading) == {
            "Rates / Metrics",
            "Rates / Curve Slopes",
            "Inflation / Metrics",
            "FX / Metrics",
            "FX / FX Carry",
            "Commodities / Metrics",
            "Equities / Metrics",
        }
        two_year = by_heading["Rates / Metrics"].rows[0]
        assert two_year["Metric"] == "US 2-Year Treasury Yield"
        assert two_year["Value"] == "4.34%"
        assert two_year["1W"] == "+10.0bp / +2.36%"
        assert two_year["As Of"] == "2026-08-31"
        assert two_year["Status"] == "Fresh"
        gold = next(r for r in by_heading["Commodities / Metrics"].rows if r["Metric"] == "Gold")
        assert gold["Value"] == "4,374.7002 USD/oz"

    def test_no_em_dash_survives_into_sections(self) -> None:
        page = read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES)
        assert page is not None
        assert "—" not in _cells(page)

    def test_raw_markdown_is_the_whole_file(self) -> None:
        page = read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES)
        assert page is not None
        assert page.raw_markdown == (_FIXTURES / "notes" / "2026-09-01.md").read_text()


# -------------------------------------------------------------------------- equity


class TestReadEquitySnapshot:
    def test_unknown_ticker_returns_none(self) -> None:
        assert read_equity_snapshot("NOPE", docs_dir=_FIXTURES) is None

    def test_ticker_with_dot_maps_to_hyphen_file(self) -> None:
        page = read_equity_snapshot("BHP.AX", docs_dir=_FIXTURES)
        assert page is not None
        assert page.doc_id == "equity_snapshot/BHP.AX"
        assert page.page_path.endswith("equities/bhp-ax.md")

    def test_all_fields_present_no_warnings(self) -> None:
        page = read_equity_snapshot("AAPL", docs_dir=_FIXTURES)
        assert page is not None
        assert page.system == "equity_snapshot"
        assert page.as_of == date(2026, 9, 1)
        assert page.stale is None
        assert page.data_warnings == []
        assert page.subject_terms == ["Apple Inc.", "AAPL"]
        by_heading = {s.heading: s for s in page.sections}
        assert [r for r in by_heading["Valuation"].rows] == [
            {"Multiple": "Trailing P/E", "Value": "37.33x"},
            {"Multiple": "Forward P/E", "Value": "34.09x"},
            {"Multiple": "EV / EBITDA", "Value": "28.38x"},
        ]
        assert by_heading["Profitability"].rows[3] == {
            "Metric": "Return on equity",
            "Value": "148.75%",
        }
        snap = {k: v for row in by_heading["Snapshot"].rows for k, v in row.items()}
        assert snap["Market capitalization"] == "USD 4.75 trillion"

    def test_suppressed_fields_dropped_reason_in_data_warnings(self) -> None:
        page = read_equity_snapshot("CBA.AX", docs_dir=_FIXTURES)
        assert page is not None
        assert page.data_warnings == [
            "Gross margin not shown: not economically meaningful for Financial Services companies.",
            "EV/EBITDA not available for this ticker.",
        ]
        by_heading = {s.heading: s for s in page.sections}
        assert [r["Multiple"] for r in by_heading["Valuation"].rows] == [
            "Trailing P/E",
            "Forward P/E",
        ]
        assert [r["Metric"] for r in by_heading["Profitability"].rows] == [
            "Operating margin",
            "Profit margin",
            "Return on equity",
        ]
        assert "—" not in _cells(page)

    def test_currency_gate_warning_covers_missing_ev_ebitda(self) -> None:
        page = read_equity_snapshot("BHP.AX", docs_dir=_FIXTURES)
        assert page is not None
        assert any("trading currency (AUD)" in w for w in page.data_warnings)

    def test_table_form_wins_over_prose_trailing_zero(self) -> None:
        page = read_equity_snapshot("MSFT", docs_dir=_FIXTURES)
        assert page is not None
        by_heading = {s.heading: s for s in page.sections}
        assert by_heading["Valuation"].rows[0] == {
            "Multiple": "Trailing P/E",
            "Value": "27.90x",
        }

    def test_missing_field_without_warning_raises(self) -> None:
        with pytest.raises(SourcePageIntegrityError) as exc:
            read_equity_snapshot("BRK", docs_dir=_BROKEN)
        assert "EV / EBITDA" in str(exc.value)

    def test_one_covered_one_uncovered_still_raises(self) -> None:
        # brk.md covers "Operating margin" but not "EV / EBITDA": the check is per field.
        with pytest.raises(SourcePageIntegrityError):
            read_equity_snapshot("BRK", docs_dir=_BROKEN)


# --------------------------------------------------------------------------- comps


class TestReadCompTable:
    def test_unknown_table_id_returns_none(self) -> None:
        assert read_comp_table("no-such-table", docs_dir=_FIXTURES) is None

    def test_registry_entry_without_published_page_returns_none(self) -> None:
        # chart-bakerhughes-wellsfargo is a real registry table but no fixture .md.
        assert read_comp_table("chart-bakerhughes-wellsfargo", docs_dir=_FIXTURES) is None

    def test_envelope_and_transaction_figures_from_registry(self) -> None:
        page = read_comp_table("splunk-cisco-qatalyst", docs_dir=_FIXTURES)
        assert page is not None
        assert page.system == "comps"
        assert page.doc_id == "comps/splunk-cisco-qatalyst"
        assert page.as_of == date(2023, 10, 30)
        assert page.stale is None
        assert page.data_warnings == []
        assert page.subject_terms == [
            "Splunk, Inc.",
            "Cisco Systems, Inc.",
            "splunk-cisco-qatalyst",
        ]
        txn = {s.heading: s for s in page.sections}["Selected Transactions Analysis"]
        new_relic = next(r for r in txn.rows if r["Target"] == "New Relic, Inc.")
        assert new_relic["NTM Revenue Multiple"] == "5.8x"
        assert new_relic["Year"] == "2023"

    def test_summary_stats_section_present_even_with_no_row_multiples(self) -> None:
        page = read_comp_table("footlocker-dicks-evercore", docs_dir=_FIXTURES)
        assert page is not None
        by_heading = {s.heading: s for s in page.sections}
        assert by_heading["Summary Statistics"].rows == [
            {
                "Benchmark": "TEV / LTM Adjusted EBITDA",
                "Mean": "7.4x",
                "Median": "6.9x",
                "Low": "3.7x",
                "High": "10.9x",
            }
        ]
        txn = by_heading["Selected Transactions Analysis"]
        assert all("Multiple" not in "".join(r) for r in txn.rows)

    def test_footnotes_and_summary_stats_for_norfolk_southern(self) -> None:
        page = read_comp_table("norfolk-southern-union-pacific-wells-fargo", docs_dir=_FIXTURES)
        assert page is not None
        by_heading = {s.heading: s for s in page.sections}
        assert by_heading["Summary Statistics"].rows[0]["Mean"] == "11.6x"
        assert {r["Ref"] for r in by_heading["Footnotes"].rows} == {"[a]", "[b]", "[c]", "[d]"}
        kcs = next(
            r
            for r in by_heading["Selected Transactions Analysis"].rows
            if r["Target"] == "Kansas City Southern"
        )
        assert kcs["TEV /LTM EBITDA Multiple"] == "19.5x"

    def test_every_multiple_in_rendered_md_is_in_the_structured_source(self) -> None:
        # Trace 1 invariant: nothing published in docs/comps/*.md is absent from FIG.
        import re

        multiple_re = re.compile(r"\d+\.\d+x")
        for table in registry.TABLES:
            md_path = _REPO_DOCS / "comps" / f"{table.table_id}.md"
            page = read_comp_table(table.table_id, docs_dir=_REPO_DOCS)
            assert page is not None, table.table_id
            structured = " ".join(_cells(page))
            for token in set(multiple_re.findall(md_path.read_text())):
                assert token in structured, f"{table.table_id}: {token} missing from SourcePage"


# ------------------------------------------------------------------------- drift


class TestDriftAgainstLiveDocs:
    def test_every_live_macro_note_parses(self) -> None:
        for path in sorted((_REPO_DOCS / "notes").glob("*.md")):
            if path.name == "index.md":
                continue
            page = read_macro_note(date.fromisoformat(path.stem), docs_dir=_REPO_DOCS)
            assert page is not None and page.sections, path.name

    def test_every_live_equity_snapshot_parses(self) -> None:
        for path in sorted((_REPO_DOCS / "equities").glob("*.md")):
            if path.name == "index.md":
                continue
            page = read_equity_snapshot(path.stem.upper().replace("-", "."), docs_dir=_REPO_DOCS)
            assert page is not None and page.sections, path.name

    def test_every_registry_table_parses(self) -> None:
        for table in registry.TABLES:
            page = read_comp_table(table.table_id, docs_dir=_REPO_DOCS)
            assert page is not None and page.sections, table.table_id


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
