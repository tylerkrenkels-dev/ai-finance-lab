"""Unit tests for the shared markdown parsers, against real committed page text."""

from pathlib import Path

import pytest

from apps.research_agent.markdown_parsing import (
    parse_bullets,
    parse_front_matter,
    parse_pipe_tables,
    split_sections,
    strip_front_matter,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_NOTE = (_FIXTURES / "notes" / "2026-09-01.md").read_text()
_EQUITY = (_FIXTURES / "equities" / "cba-ax.md").read_text()


class TestParseFrontMatter:
    def test_reads_flat_scalars_and_strips_quotes(self) -> None:
        fm = parse_front_matter(_EQUITY)
        assert fm == {
            "title": "Commonwealth Bank of Australia (CBA.AX) — Equity Snapshot",
            "date": "2026-09-02",
            "description": (
                "Commonwealth Bank trades at a modest premium with solid profitability metrics"
            ),
            "ticker": "CBA.AX",
            "currency": "AUD",
        }

    def test_reads_unquoted_boolean_like_value(self) -> None:
        assert parse_front_matter(_NOTE)["stale"] == "true"

    def test_no_front_matter_returns_empty(self) -> None:
        assert parse_front_matter("# Just a heading\n\nbody") == {}

    def test_value_containing_colon_space_keeps_full_value(self) -> None:
        text = '---\ntitle: "A: B"\n---\n\nbody\n'
        assert parse_front_matter(text)["title"] == "A: B"


class TestStripFrontMatter:
    def test_removes_leading_block(self) -> None:
        assert strip_front_matter(_EQUITY).startswith(
            "# Commonwealth Bank trades at a modest premium"
        )

    def test_noop_without_block(self) -> None:
        assert strip_front_matter("# H\n\nbody") == "# H\n\nbody"


class TestSplitSections:
    def test_qualifies_h3_with_parent_h2_and_drops_preamble(self) -> None:
        headings = [h for h, _ in split_sections(strip_front_matter(_NOTE))]
        assert headings == [
            "Data Warnings",
            "Rates / Metrics",
            "Rates / Curve Slopes",
            "Inflation / Metrics",
            "FX / Metrics",
            "FX / FX Carry",
            "Commodities / Metrics",
            "Equities / Metrics",
        ]

    def test_equity_sections_are_flat_h2(self) -> None:
        headings = [h for h, _ in split_sections(strip_front_matter(_EQUITY))]
        assert headings == ["Snapshot", "Data Warnings", "Valuation", "Profitability"]

    def test_body_is_scoped_to_its_own_section(self) -> None:
        sections = dict(split_sections(strip_front_matter(_NOTE)))
        assert "US 2-Year Treasury Yield" in sections["Rates / Metrics"]
        assert "US 2-Year Treasury Yield" not in sections["Inflation / Metrics"]


class TestParsePipeTables:
    def test_reads_rows_keyed_by_header(self) -> None:
        body = dict(split_sections(strip_front_matter(_NOTE)))["Rates / Curve Slopes"]
        tables = parse_pipe_tables(body)
        assert len(tables) == 1
        assert tables[0][0] == {
            "Slope": "US 2s10s Slope",
            "Spread (bp)": "+41.0bp",
            "As Of (1st leg)": "2026-08-31",
            "As Of (2nd leg)": "2026-08-31",
        }

    def test_finds_multiple_tables_in_one_body(self) -> None:
        # A section body that still contains two ### subtables when H3 splitting is
        # bypassed: parse the whole "Rates" H2 body directly.
        rates_h2 = strip_front_matter(_NOTE).split("## Rates\n", 1)[1].split("\n## ", 1)[0]
        assert len(parse_pipe_tables(rates_h2)) == 2

    def test_preserves_verbatim_cell_including_em_dash(self) -> None:
        body = dict(split_sections(strip_front_matter(_EQUITY)))["Valuation"]
        rows = parse_pipe_tables(body)[0]
        assert rows == [
            {"Multiple": "Trailing P/E", "Value": "24.23x"},
            {"Multiple": "Forward P/E", "Value": "23.25x"},
            {"Multiple": "EV / EBITDA", "Value": "—"},
        ]

    def test_no_table_returns_empty_list(self) -> None:
        body = dict(split_sections(strip_front_matter(_EQUITY)))["Data Warnings"]
        assert parse_pipe_tables(body) == []


class TestParseBullets:
    def test_strips_marker(self) -> None:
        body = dict(split_sections(strip_front_matter(_EQUITY)))["Data Warnings"]
        assert parse_bullets(body) == [
            "Gross margin not shown: not economically meaningful for Financial Services companies.",
            "EV/EBITDA not available for this ticker.",
        ]

    def test_ignores_non_bullet_lines(self) -> None:
        assert parse_bullets("intro para\n\n- one\n- two\n\ntrailing") == ["one", "two"]

    def test_empty_without_bullets(self) -> None:
        assert parse_bullets("no bullets here") == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
