import re

import markdown
import pytest

from apps.comps.models import ComparableTransactionsTable, Deal
from apps.comps.registry import DEALS, TABLES
from apps.comps.render import render_table, table_filename

_DEAL_BY_ID = {d.deal_id: d for d in DEALS}


def _table(table_id: str) -> ComparableTransactionsTable:
    return next(t for t in TABLES if t.table_id == table_id)


def _deal_for(table_id: str) -> Deal:
    return _DEAL_BY_ID[_table(table_id).deal_id]


def test_table_filename_is_the_table_id() -> None:
    assert table_filename(_table("splunk-cisco-qatalyst")) == "splunk-cisco-qatalyst.md"


def test_render_table_includes_front_matter() -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert rendered.startswith("---\n")
    assert (
        'title: "Splunk, Inc. / Cisco Systems, Inc. — Selected Transactions Analysis"' in rendered
    )
    assert "date: 2023-10-30" in rendered  # source.filed_date, not today
    assert 'status: "completed"' in rendered


def test_render_table_advisor_possessive_handles_trailing_s() -> None:
    # "Qatalyst Partners" already ends in "s" -- must render "Qatalyst Partners'",
    # not the grammatically wrong "Qatalyst Partners's".
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert "Qatalyst Partners'" in rendered
    assert "Qatalyst Partners's" not in rendered


def test_render_table_includes_deal_context_for_completed_deal() -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert "- **Target:** Splunk, Inc." in rendered
    assert "- **Acquiror:** Cisco Systems, Inc." in rendered
    assert "- **Status:** Completed" in rendered
    assert "- **Announced:** 2023-09-20" in rendered
    assert "- **Completed:** 2024-03-18" in rendered


def test_render_table_pending_deal_shows_bold_marker_and_omits_completed_line() -> None:
    table = _table("norfolk-southern-union-pacific-wells-fargo")
    deal = _deal_for("norfolk-southern-union-pacific-wells-fargo")

    rendered = render_table(table, deal)

    assert "- **Status:** **Pending**" in rendered
    assert "- **Completed:**" not in rendered


def test_render_table_includes_source_citation() -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert (
        "[Splunk, Inc. DEFM14A]"
        "(https://www.sec.gov/Archives/edgar/data/1353283/000114036123050211/ny20011269x2_defm14a.htm)"
        in rendered
    )
    assert "0001140361-23-050211" in rendered


def test_render_table_splunk_has_three_multiple_columns() -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert (
        "| Announcement | Target | Acquiror | NTM Revenue Multiple "
        "| NTM EBITDA Multiple | NTM LFCF Multiple |"
    ) in rendered
    assert (
        "| 07/31/23 | New Relic, Inc. | Francisco Partners Management, L.P. & TPG Fund "
        "| 5.8x | 30.4x | 48.1x |"
    ) in rendered


def test_render_table_chart_has_bare_three_column_table_with_no_multiples() -> None:
    table = _table("chart-bakerhughes-wellsfargo")
    deal = _deal_for("chart-bakerhughes-wellsfargo")

    rendered = render_table(table, deal)

    assert "| Announcement | Target | Acquiror |\n" in rendered
    assert "| November 2022 | Howden | Chart Industries, Inc. |" in rendered
    assert "### Summary Statistics" not in rendered
    assert "## Footnotes" not in rendered


def test_render_table_foot_locker_has_summary_stats_but_no_footnotes_section() -> None:
    table = _table("footlocker-dicks-evercore")
    deal = _deal_for("footlocker-dicks-evercore")

    rendered = render_table(table, deal)

    assert "### Summary Statistics" in rendered
    assert "| Benchmark | Mean | Median | Low | High |" in rendered
    assert "| TEV / LTM Adjusted EBITDA | 7.4x | 6.9x | 3.7x | 10.9x |" in rendered
    assert "## Footnotes" not in rendered


def test_render_table_splunk_has_no_summary_stats_section() -> None:
    table = _table("splunk-cisco-qatalyst")
    deal = _deal_for("splunk-cisco-qatalyst")

    rendered = render_table(table, deal)

    assert "### Summary Statistics" not in rendered


def test_render_table_wells_fargo_footnotes_section_lists_all_refs() -> None:
    table = _table("norfolk-southern-union-pacific-wells-fargo")
    deal = _deal_for("norfolk-southern-union-pacific-wells-fargo")

    rendered = render_table(table, deal)

    assert "## Footnotes" in rendered
    assert "- **[a]** EBITDA adjusted for the estimated impact of COVID-19." in rendered
    assert "- **[d]**" in rendered


def test_render_table_wells_fargo_footnote_marker_is_appended_to_the_multiple_cell() -> None:
    # Wells Fargo's "[a]" never appears in target/acquiror text, so it must be
    # appended to the row to be visible at all.
    table = _table("norfolk-southern-union-pacific-wells-fargo")
    deal = _deal_for("norfolk-southern-union-pacific-wells-fargo")

    rendered = render_table(table, deal)

    assert (
        "| 2021 | Kansas City Southern | Canadian Pacific Railway Limited | 19.5x [a] |" in rendered
    )


def test_render_table_bofa_inline_footnote_marker_is_not_duplicated() -> None:
    # BofA's "(1)" is already embedded in the acquiror text ("Rail Consortium (1)");
    # it must appear exactly once in the row, not also appended to the multiple cell.
    table = _table("norfolk-southern-union-pacific-bofa")
    deal = _deal_for("norfolk-southern-union-pacific-bofa")

    rendered = render_table(table, deal)
    row = next(line for line in rendered.splitlines() if "Pacific National Holdings" in line)

    assert row == "| 03/16 | Pacific National Holdings Pty Ltd. | Rail Consortium (1) | 10.3x |"
    assert row.count("(1)") == 1


@pytest.mark.parametrize("table_id", [t.table_id for t in TABLES])
def test_render_table_headings_are_separated_by_blank_lines(table_id: str) -> None:
    """A heading immediately following a list/table with no blank line can fail to
    parse under Python-Markdown (what MkDocs uses) -- regression guard for that,
    mirroring apps/macro_note's test of the same name."""
    table = _table(table_id)
    deal = _DEAL_BY_ID[table.deal_id]

    rendered = render_table(table, deal)

    for match in re.finditer(r"^(#{1,3} .+)$", rendered, re.MULTILINE):
        if match.start() == 0:
            continue
        prefix = rendered[max(0, match.start() - 2) : match.start()]
        assert prefix == "\n\n", f"{table_id}: no blank line before {match.group(1)!r}"


@pytest.mark.parametrize("table_id", [t.table_id for t in TABLES])
def test_render_table_survives_real_markdown_parsing(table_id: str) -> None:
    """Round-trips the rendered output through the real `markdown` package (what
    MkDocs uses), the same verification discipline used for macro_note's renderer
    (#21/#36) -- confirms headings and tables actually parse, not just look right."""
    table = _table(table_id)
    deal = _DEAL_BY_ID[table.deal_id]

    rendered = render_table(table, deal)
    html = markdown.markdown(rendered, extensions=["tables"])

    assert f"<h1>{deal.target_name} / {deal.acquiror_name}</h1>" in html
    assert "<h2>Deal</h2>" in html
    assert "<h2>Source</h2>" in html
    assert "<table>" in html
