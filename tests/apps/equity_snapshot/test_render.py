"""Renderer tests for the equity snapshot page.

Real BHP.AX / JPM / AAPL fundamentals from test_calculations.py, run through
build_equity_snapshot. BHP is the currency-gated case (enterprise_to_ebitda
None because trading currency != reporting currency); JPM is the
sector-suppressed case (gross_margin_pct None because it is a bank); AAPL is
the clean case (every field present, no data_warnings).
"""

import re

import markdown
import pytest

from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import build_equity_snapshot
from apps.equity_snapshot.render import render_snapshot, snapshot_filename
from tests.apps.equity_snapshot.test_calculations import _AAPL, _BHP, _JPM

_BHP_SNAPSHOT = build_equity_snapshot(_BHP)
_JPM_SNAPSHOT = build_equity_snapshot(_JPM)
_AAPL_SNAPSHOT = build_equity_snapshot(_AAPL)

_NARRATIVE = TickerNarrative(
    headline="A concise valuation and profitability readout",
    summary="The company trades on the multiples and margins tabulated below.",
)


# --- snapshot_filename ---


def test_snapshot_filename_slugs_the_ticker() -> None:
    assert snapshot_filename("BHP.AX") == "bhp-ax.md"
    assert snapshot_filename("JPM") == "jpm.md"


# --- front matter ---


def test_render_snapshot_front_matter() -> None:
    rendered = render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)

    assert rendered.startswith("---\n")
    assert 'title: "BHP Group Limited (BHP.AX) — Equity Snapshot"' in rendered
    assert "date: 2026-08-24" in rendered  # snapshot.as_of date, not today
    assert f'description: "{_NARRATIVE.headline}"' in rendered
    assert 'ticker: "BHP.AX"' in rendered
    assert 'currency: "AUD"' in rendered


# --- headline + summary ---


def test_render_snapshot_headline_and_summary() -> None:
    rendered = render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)

    assert f"# {_NARRATIVE.headline}" in rendered
    assert _NARRATIVE.summary in rendered


# --- Snapshot list ---


def test_render_snapshot_snapshot_list_bhp() -> None:
    rendered = render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)

    assert "- **Company:** BHP Group Limited" in rendered
    assert "- **Ticker:** BHP.AX" in rendered
    assert "- **Sector:** Basic Materials" in rendered
    assert "- **Price:** AUD 67.10" in rendered
    assert "- **Market capitalization:** AUD 340.88 billion" in rendered
    assert "- **As of:** 2026-08-24" in rendered


def test_render_snapshot_none_sector_renders_em_dash_never_blank() -> None:
    snapshot = build_equity_snapshot(_AAPL.model_copy(update={"sector": None}))

    rendered = render_snapshot(snapshot, _NARRATIVE)

    assert "- **Sector:** —" in rendered
    assert "- **Sector:** \n" not in rendered
    assert "- **Sector:**\n" not in rendered


def test_render_snapshot_market_cap_none_renders_em_dash() -> None:
    snapshot = build_equity_snapshot(_AAPL.model_copy(update={"market_cap": None}))

    rendered = render_snapshot(snapshot, _NARRATIVE)

    assert snapshot.market_cap_display is None
    assert "- **Market capitalization:** —" in rendered


# --- Valuation table + the currency-gated None case (BHP) ---


def test_render_snapshot_valuation_table_bhp_currency_gated_ev_ebitda_is_em_dash() -> None:
    rendered = render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)

    assert "## Valuation" in rendered
    assert "| Multiple | Value |" in rendered
    assert "| Trailing P/E | 24.76x |" in rendered
    assert "| Forward P/E | 18.62x |" in rendered
    assert "| EV / EBITDA | — |" in rendered

    # The "—" is explained in the always-rendered Data Warnings section, authored
    # in payload.py where the currency policy lives -- not classified in the cell.
    assert "## Data Warnings" in rendered
    assert "trading currency (AUD) differs from its reporting currency (USD)" in rendered


# --- Profitability table (BHP: all present) ---


def test_render_snapshot_profitability_table_bhp() -> None:
    rendered = render_snapshot(_BHP_SNAPSHOT, _NARRATIVE)

    assert "## Profitability" in rendered
    assert "| Metric | Value |" in rendered
    assert "| Gross margin | 85.92% |" in rendered
    assert "| Operating margin | 43.34% |" in rendered
    assert "| Profit margin | 16.73% |" in rendered
    assert "| Return on equity | 24.00% |" in rendered


# --- The sector-suppressed None case (JPM) ---


def test_render_snapshot_jpm_sector_suppressed_gross_margin_is_em_dash_and_explained() -> None:
    rendered = render_snapshot(_JPM_SNAPSHOT, _NARRATIVE)

    assert "| Gross margin | — |" in rendered
    assert "| Operating margin | 50.39% |" in rendered
    assert "| Return on equity | 17.79% |" in rendered
    assert "| EV / EBITDA | — |" in rendered

    assert "## Data Warnings" in rendered
    assert "not economically meaningful for Financial Services companies." in rendered
    assert "EV/EBITDA not available for this ticker." in rendered


# --- Data Warnings section omitted when there are none (AAPL) ---


def test_render_snapshot_data_warnings_section_omitted_when_none() -> None:
    assert _AAPL_SNAPSHOT.data_warnings == []

    rendered = render_snapshot(_AAPL_SNAPSHOT, _NARRATIVE)

    assert "## Data Warnings" not in rendered
    assert "## Valuation" in rendered
    assert "| EV / EBITDA | 27.01x |" in rendered
    # A blank line still precedes ## Valuation with the optional section absent.
    index = rendered.index("## Valuation")
    assert rendered[index - 2 : index] == "\n\n"


# --- Blank line before every heading (#21/#36) ---


@pytest.mark.parametrize(
    "snapshot", [_BHP_SNAPSHOT, _JPM_SNAPSHOT, _AAPL_SNAPSHOT], ids=["bhp", "jpm", "aapl"]
)
def test_render_snapshot_headings_are_separated_by_blank_lines(snapshot: object) -> None:
    """A heading immediately following a list/table with no blank line can fail to
    parse under Python-Markdown (what MkDocs uses) -- regression guard, mirroring
    the same test in apps/macro_note and apps/comps."""
    rendered = render_snapshot(snapshot, _NARRATIVE)  # type: ignore[arg-type]

    for match in re.finditer(r"^(#{1,3} .+)$", rendered, re.MULTILINE):
        if match.start() == 0:
            continue
        prefix = rendered[max(0, match.start() - 2) : match.start()]
        assert prefix == "\n\n", f"no blank line before {match.group(1)!r}"


@pytest.mark.parametrize(
    "snapshot", [_BHP_SNAPSHOT, _JPM_SNAPSHOT, _AAPL_SNAPSHOT], ids=["bhp", "jpm", "aapl"]
)
def test_render_snapshot_survives_real_markdown_parsing(snapshot: object) -> None:
    """Round-trip through the real `markdown` package (what MkDocs uses), the same
    verification discipline used for macro_note's renderer (#21/#36)."""
    rendered = render_snapshot(snapshot, _NARRATIVE)  # type: ignore[arg-type]

    html = markdown.markdown(rendered, extensions=["tables"])

    assert f"<h1>{_NARRATIVE.headline}</h1>" in html
    assert "<h2>Snapshot</h2>" in html
    assert "<h2>Valuation</h2>" in html
    assert "<h2>Profitability</h2>" in html
    assert "<table>" in html
