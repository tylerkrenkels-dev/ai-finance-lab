"""Renders an EquitySnapshot + TickerNarrative into the published markdown page.

Pure text transformation -- no file I/O. render_snapshot() returns markdown
text; snapshot_filename() returns the canonical filename it should be published
under (docs/equities/<snapshot_filename(ticker)>). Actually writing that file
is an orchestration concern, not a rendering one, and belongs to a future
issue -- the same split apps/macro_note/render.py draws from
apps/macro_note/publish.py.

Every markdown table row, header, and separator is built here in Python, not as
inline Jinja {% for %} loops over cells in the template. trim_blocks strips the
newline immediately following any {% %} tag, which collapses inline-loop table
rows onto a single line (discovered building apps/comps/render.py against real
registry data). {{ expression }} tags are unaffected, so the template only ever
interpolates already-complete lines, and every section's block emits a trailing
blank line so the next heading is always preceded by "\\n\\n" (the #21/#36
lesson: a heading with no blank line before it can fail to parse under
Python-Markdown, which is what MkDocs uses).

A None valuation/profitability field renders as an em-dash. The renderer does
NOT classify WHY the field is None. Whether gross_margin_pct was suppressed
because the sector makes it meaningless, or enterprise_to_ebitda was gated
because the trading and reporting currencies differ, is a policy decision owned
by calculations.py and already turned into a full-sentence data_warning by
payload.py. The renderer could not re-derive it even if it wanted to --
EquitySnapshot does not carry financial_currency -- so the "## Data Warnings"
section (always rendered when non-empty, immediately before the tables) is the
single place a "—" is explained, authored in the layer that owns the policy.
This mirrors apps/macro_note: a "**Stale**" cell marker plus a Data Warnings
section that carries the detail.

autoescape is off: this renders markdown/plain text, not HTML, so there is no
XSS surface -- and HTML-escaping would corrupt content held verbatim on
purpose, e.g. the "&" in "JPMorgan Chase & Co." (-> "&amp;") or an apostrophe
in narrative prose (-> "&#39;").
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from apps.equity_snapshot.calculations import ProfitabilityMetrics, ValuationMultiples
from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import EquitySnapshot

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "snapshot.md.j2"

_EM_DASH = "—"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_snapshot(snapshot: EquitySnapshot, narrative: TickerNarrative) -> str:
    """Render `snapshot` and `narrative` into the published markdown page text."""
    template = _env.get_template(_TEMPLATE_NAME)
    return template.render(
        snapshot=snapshot,
        narrative=narrative,
        page_title=_page_title(snapshot),
        snapshot_date=snapshot.as_of.date().isoformat(),
        snapshot_lines=_snapshot_lines(snapshot),
        valuation_header=_md_row(["Multiple", "Value"]),
        valuation_separator=_md_row(["---", "---"]),
        valuation_rows=_valuation_rows(snapshot.valuation),
        profitability_header=_md_row(["Metric", "Value"]),
        profitability_separator=_md_row(["---", "---"]),
        profitability_rows=_profitability_rows(snapshot.profitability),
    )


def snapshot_filename(ticker: str) -> str:
    """Canonical filename for a snapshot, e.g. "bhp-ax.md" -- lives under docs/equities/."""
    return f"{ticker.lower().replace('.', '-')}.md"


def _page_title(snapshot: EquitySnapshot) -> str:
    return f"{snapshot.company_name} ({snapshot.ticker}) — Equity Snapshot"


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _snapshot_lines(snapshot: EquitySnapshot) -> list[str]:
    sector = snapshot.sector if snapshot.sector is not None else _EM_DASH
    market_cap = (
        snapshot.market_cap_display if snapshot.market_cap_display is not None else _EM_DASH
    )
    return [
        f"- **Company:** {snapshot.company_name}",
        f"- **Ticker:** {snapshot.ticker}",
        f"- **Sector:** {sector}",
        f"- **Price:** {snapshot.currency} {snapshot.current_price:.2f}",
        f"- **Market capitalization:** {market_cap}",
        f"- **As of:** {snapshot.as_of.date().isoformat()}",
    ]


def _multiple(value: float | None) -> str:
    return _EM_DASH if value is None else f"{value:.2f}x"


def _percent(value: float | None) -> str:
    return _EM_DASH if value is None else f"{value:.2f}%"


def _valuation_rows(valuation: ValuationMultiples) -> list[str]:
    return [
        _md_row(["Trailing P/E", _multiple(valuation.trailing_pe)]),
        _md_row(["Forward P/E", _multiple(valuation.forward_pe)]),
        _md_row(["EV / EBITDA", _multiple(valuation.enterprise_to_ebitda)]),
    ]


def _profitability_rows(profitability: ProfitabilityMetrics) -> list[str]:
    return [
        _md_row(["Gross margin", _percent(profitability.gross_margin_pct)]),
        _md_row(["Operating margin", _percent(profitability.operating_margin_pct)]),
        _md_row(["Profit margin", _percent(profitability.profit_margin_pct)]),
        _md_row(["Return on equity", _percent(profitability.return_on_equity_pct)]),
    ]
