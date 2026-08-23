"""Renders a ComparableTransactionsTable + its Deal into the published markdown page.

Pure text transformation -- no file I/O. render_table() returns markdown text;
table_filename() returns the canonical filename it should be published under
(docs/comps/<table_filename(table)>). Actually writing that file is an
orchestration concern, not a rendering one, and belongs to a future issue --
the same split apps/macro_note/render.py draws from apps/macro_note/publish.py.

Every markdown table row is built here in Python, not as inline Jinja
{% for %} loops in the template. trim_blocks strips the newline immediately
following ANY block tag, including one that ends a content line rather than
sitting alone on its own line -- e.g. "| a |{% for x in cols %} {{ x }} |
{% endfor %}\\nnext line" renders with the trailing "{% endfor %}" eating the
newline before "next line", collapsing every table row onto a single line.
(Confirmed directly: Environment(trim_blocks=True).from_string("a |{% for x
in [1,2] %} {{x}} |{% endfor %}\\nb").render() == "a | 1 | 2 |b" -- caught by
actually rendering real registry data during this issue, not by inspection.)
{{ expression }} tags are not affected by trim_blocks, only {% statement %}
tags are, so every row is precomputed as a plain string and the template only
ever interpolates already-complete lines.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from apps.comps.models import ComparableTransactionRow, ComparableTransactionsTable, Deal

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "comp_table.md.j2"

# autoescape is off: this renders markdown/plain text, not HTML, so there is no XSS
# surface -- and it matters more here than in macro_note's renderer, since
# HTML-escaping would turn the curly quotes and apostrophes preserved on purpose in
# the registry (e.g. "Chico's", "Baker Hughes Company's") into HTML entities,
# corrupting both the rendered page and any future guard check against the frozen
# fixtures those characters were transcribed from.
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_table(table: ComparableTransactionsTable, deal: Deal) -> str:
    """Render `table` and its `deal` into the published markdown page text."""
    template = _env.get_template(_TEMPLATE_NAME)
    stat_columns = _summary_stat_columns(table)
    return template.render(
        table=table,
        deal=deal,
        advisor_possessive=_possessive(table.advisor),
        target_possessive=_possessive(deal.target_name),
        comp_table_header=_comp_table_header(table),
        comp_table_separator=_comp_table_separator(table),
        comp_table_rows=_comp_table_rows(table),
        summary_stats_header=_summary_stats_header(stat_columns),
        summary_stats_separator=_summary_stats_separator(stat_columns),
        summary_stats_rows=_summary_stats_rows(table, stat_columns),
    )


def table_filename(table: ComparableTransactionsTable) -> str:
    """Canonical filename for a table, e.g. "splunk-cisco-qatalyst.md" -- under docs/comps/."""
    return f"{table.table_id}.md"


def _possessive(name: str) -> str:
    """ "Qatalyst Partners" -> "Qatalyst Partners'"; "Splunk, Inc." -> "Splunk, Inc.'s"."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _summary_stat_columns(table: ComparableTransactionsTable) -> list[str]:
    """Column set for the Summary Statistics table: the union of every stat row's
    keys, in first-seen order -- so a table with more than one summary_stats entry
    (none currently in the registry) still renders one consistent header, with a
    "—" filled in for any row missing a given column, rather than assuming every
    entry shares the same keys."""
    if not table.summary_stats:
        return []
    columns: list[str] = []
    for values in table.summary_stats.values():
        for key in values:
            if key not in columns:
                columns.append(key)
    return columns


def _visible_footnote_refs(row: ComparableTransactionRow) -> list[str]:
    """footnote_refs not already visible as a substring of target/acquiror.

    BofA's Norfolk Southern row embeds its marker directly in the acquiror text
    ("Rail Consortium (1)"); appending footnote_refs there too would print "(1)"
    twice. Wells Fargo's markers ("[a]"-"[d]") never appear in any other field on
    their rows, so they need to be appended to the rendered row to be visible at
    all.
    """
    return [ref for ref in row.footnote_refs if ref not in row.target and ref not in row.acquiror]


def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _comp_table_header(table: ComparableTransactionsTable) -> str:
    return _md_row(["Announcement", "Target", "Acquiror", *table.multiple_columns])


def _comp_table_separator(table: ComparableTransactionsTable) -> str:
    return _md_row(["---"] * (3 + len(table.multiple_columns)))


def _comp_table_rows(table: ComparableTransactionsTable) -> list[str]:
    lines = []
    n_multiples = len(table.multiple_columns)
    for row in table.rows:
        refs = _visible_footnote_refs(row)
        refs_suffix = f" {' '.join(refs)}" if refs else ""
        acquiror_cell = row.acquiror + (refs_suffix if n_multiples == 0 else "")
        cells = [row.announcement_period_raw, row.target, acquiror_cell]
        for i, col in enumerate(table.multiple_columns):
            value = row.multiples.get(col)
            cell = value if value is not None else "—"
            if i == n_multiples - 1:
                cell += refs_suffix
            cells.append(cell)
        lines.append(_md_row(cells))
    return lines


def _summary_stats_header(stat_columns: list[str]) -> str:
    return _md_row(["Benchmark", *stat_columns])


def _summary_stats_separator(stat_columns: list[str]) -> str:
    return _md_row(["---"] * (1 + len(stat_columns)))


def _summary_stats_rows(table: ComparableTransactionsTable, stat_columns: list[str]) -> list[str]:
    if not table.summary_stats:
        return []
    return [
        _md_row([label, *(values.get(col, "—") for col in stat_columns)])
        for label, values in table.summary_stats.items()
    ]
