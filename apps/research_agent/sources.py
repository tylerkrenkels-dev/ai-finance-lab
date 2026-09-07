"""Source-reading tools: one function per live system, all returning a SourcePage.

``read_macro_note`` / ``read_equity_snapshot`` parse the committed markdown a
human reads on the site; ``read_comp_table`` builds from the importable
``apps.comps.registry`` and only reads the published page for ``raw_markdown``,
returning None when that page does not exist (a citation must resolve).

Missingness rule (equity): ``apps.equity_snapshot.payload`` guarantees a specific
``data_warnings`` entry for every ``None`` field. ``read_equity_snapshot`` asserts
it -- a "not shown" em-dash with no explaining warning raises
``SourcePageIntegrityError``, since that means an upstream render regression or a
bug here and must be loud, not degraded into a vaguer answer.

Discovery (``list_available_sources``) lives in ``apps.research_agent.discovery``.
"""

import logging
import re
from datetime import date
from pathlib import Path

from apps.comps import registry
from apps.comps.models import ComparableTransactionRow, ComparableTransactionsTable, Deal
from apps.research_agent.markdown_parsing import (
    parse_bullets,
    parse_front_matter,
    parse_pipe_tables,
    split_sections,
    strip_front_matter,
)
from apps.research_agent.models import Section, SourcePage

logger = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = Path("docs")

_EM_DASH = "—"
_KV_BULLET_RE = re.compile(r"^\*\*(?P<key>[^:]+):\*\*\s*(?P<value>.*)$")

# Equity table label -> the token that must appear in a data_warnings entry when
# that field is "not shown". The renderer prints "EV / EBITDA" (spaced) but
# payload.py writes the warning as "EV/EBITDA".
_EQUITY_FIELD_WARNING_TOKENS = {
    "Trailing P/E": "Trailing P/E",
    "Forward P/E": "Forward P/E",
    "EV / EBITDA": "EV/EBITDA",
    "Gross margin": "Gross margin",
    "Operating margin": "Operating margin",
    "Profit margin": "Profit margin",
    "Return on equity": "Return on equity",
}


class SourcePageIntegrityError(RuntimeError):
    """An equity page has a "not shown" field with no data_warnings entry to explain it.

    payload.py guarantees every ``None`` field is accompanied by a specific
    warning, so this is an upstream rendering regression or a parsing bug here --
    either way it must fail loudly rather than degrade to a vaguer answer.
    """


def read_macro_note(note_date: date, docs_dir: Path = DEFAULT_DOCS_DIR) -> SourcePage | None:
    """Read the published macro note for `note_date`, or None if there is none."""
    path = docs_dir / "notes" / f"{note_date.isoformat()}.md"
    if not path.is_file():
        return None
    text = path.read_text()
    front_matter = parse_front_matter(text)

    data_warnings: list[str] = []
    sections: list[Section] = []
    for heading, body in split_sections(strip_front_matter(text)):
        if heading == "Data Warnings":
            data_warnings = parse_bullets(body)
            continue
        rows = [
            cleaned
            for table in parse_pipe_tables(body)
            for row in table
            if (cleaned := _without_missing_cells(row))
        ]
        if rows:
            sections.append(Section(heading=heading, rows=rows))

    return SourcePage(
        system="macro_note",
        doc_id=f"macro_note/{note_date.isoformat()}",
        page_path=str(path),
        subject_terms=[],
        as_of=date.fromisoformat(front_matter.get("date", note_date.isoformat())),
        stale=front_matter.get("stale") == "true",
        data_warnings=data_warnings,
        sections=sections,
        raw_markdown=text,
    )


def read_equity_snapshot(ticker: str, docs_dir: Path = DEFAULT_DOCS_DIR) -> SourcePage | None:
    """Read the published equity snapshot for `ticker`, or None if there is none.

    Raises SourcePageIntegrityError if a valuation/profitability field is "not
    shown" with no data_warnings entry explaining it.
    """
    path = docs_dir / "equities" / f"{ticker.lower().replace('.', '-')}.md"
    if not path.is_file():
        return None
    text = path.read_text()
    front_matter = parse_front_matter(text)
    parsed = _parse_equity_body(strip_front_matter(text))

    _assert_warnings_explain_missing(
        _missing_equity_fields(parsed.valuation + parsed.profitability),
        parsed.data_warnings,
        str(path),
    )

    ticker_id = front_matter.get("ticker", ticker)
    company = _snapshot_value(parsed.snapshot, "Company")
    return SourcePage(
        system="equity_snapshot",
        doc_id=f"equity_snapshot/{ticker_id}",
        page_path=str(path),
        subject_terms=[term for term in (company, ticker_id) if term],
        as_of=date.fromisoformat(front_matter["date"]),
        stale=None,
        data_warnings=parsed.data_warnings,
        sections=_equity_sections(parsed),
        raw_markdown=text,
    )


def read_comp_table(table_id: str, docs_dir: Path = DEFAULT_DOCS_DIR) -> SourcePage | None:
    """Build a SourcePage for the comps table `table_id` from the registry.

    Returns None if `table_id` is not in the registry, or if it is but has no
    published page under `docs_dir` for the citation to resolve to.
    """
    table = next((t for t in registry.TABLES if t.table_id == table_id), None)
    if table is None:
        return None
    path = docs_dir / "comps" / f"{table_id}.md"
    if not path.is_file():
        return None
    deal = next(d for d in registry.DEALS if d.deal_id == table.deal_id)

    return SourcePage(
        system="comps",
        doc_id=f"comps/{table_id}",
        page_path=str(path),
        subject_terms=[deal.target_name, deal.acquiror_name, table_id],
        as_of=table.source.filed_date,
        stale=None,
        data_warnings=[],
        sections=_comp_sections(table, deal),
        raw_markdown=path.read_text(),
    )


class _EquityBody:
    """The four structured blocks parsed from an equity page body."""

    def __init__(self) -> None:
        self.data_warnings: list[str] = []
        self.snapshot: list[dict[str, str]] = []
        self.valuation: list[dict[str, str]] = []
        self.profitability: list[dict[str, str]] = []


def _parse_equity_body(body: str) -> _EquityBody:
    parsed = _EquityBody()
    for heading, section_body in split_sections(body):
        if heading == "Data Warnings":
            parsed.data_warnings = parse_bullets(section_body)
        elif heading == "Snapshot":
            parsed.snapshot = [_kv_bullet(b) for b in parse_bullets(section_body)]
        elif heading == "Valuation":
            parsed.valuation = _first_table(section_body)
        elif heading == "Profitability":
            parsed.profitability = _first_table(section_body)
    return parsed


def _equity_sections(parsed: _EquityBody) -> list[Section]:
    sections: list[Section] = []
    if parsed.snapshot:
        sections.append(Section(heading="Snapshot", rows=parsed.snapshot))
    for heading, raw_rows in (
        ("Valuation", parsed.valuation),
        ("Profitability", parsed.profitability),
    ):
        shown = [row for row in raw_rows if row.get("Value") != _EM_DASH]
        if shown:
            sections.append(Section(heading=heading, rows=shown))
    return sections


def _comp_sections(table: ComparableTransactionsTable, deal: Deal) -> list[Section]:
    deal_row = {
        "Target": deal.target_name,
        "Acquiror": deal.acquiror_name,
        "Status": deal.status.capitalize(),
        "Announced": deal.announced_date.isoformat(),
    }
    if deal.completed_date is not None:
        deal_row["Completed"] = deal.completed_date.isoformat()

    source = table.source
    source_row = {
        "Filing": f"{source.company_name} DEFM14A",
        "Filed": source.filed_date.isoformat(),
        "Accession": source.accession_number,
        "CIK": source.cik,
        "Section": source.section_heading,
        "Advisor": table.advisor,
        "URL": source.document_url,
    }
    sections = [
        Section(heading="Deal", rows=[deal_row]),
        Section(heading=table.analysis_label, rows=[_comp_row(r, table) for r in table.rows]),
    ]
    if table.summary_stats:
        stat_rows = [{"Benchmark": n, **v} for n, v in table.summary_stats.items()]
        sections.append(Section(heading="Summary Statistics", rows=stat_rows))
    if table.footnotes:
        note_rows = [{"Ref": ref, "Note": note} for ref, note in table.footnotes.items()]
        sections.append(Section(heading="Footnotes", rows=note_rows))
    sections.append(Section(heading="Source", rows=[source_row]))
    return sections


def _comp_row(row: ComparableTransactionRow, table: ComparableTransactionsTable) -> dict[str, str]:
    cells = {
        "Announcement": row.announcement_period_raw,
        "Year": str(row.announcement_year),
        "Target": row.target,
        "Acquiror": row.acquiror,
    }
    for column in table.multiple_columns:
        value = row.multiples.get(column)
        if value is not None:
            cells[column] = value
    if row.footnote_refs:
        cells["Footnote refs"] = " ".join(row.footnote_refs)
    return cells


def _without_missing_cells(row: dict[str, str]) -> dict[str, str]:
    """Drop cells whose value is a "not shown" em-dash. Empty if only a label remains."""
    kept = {key: value for key, value in row.items() if value != _EM_DASH}
    return kept if len(kept) >= 2 else {}


def _first_table(body: str) -> list[dict[str, str]]:
    tables = parse_pipe_tables(body)
    return tables[0] if tables else []


def _kv_bullet(bullet: str) -> dict[str, str]:
    """``**Company:** Apple Inc.`` -> ``{"Company": "Apple Inc."}``; else ``{"item": ...}``."""
    match = _KV_BULLET_RE.match(bullet)
    if match is None:
        return {"item": bullet}
    return {match.group("key").strip(): match.group("value").strip()}


def _snapshot_value(rows: list[dict[str, str]], key: str) -> str | None:
    for row in rows:
        if key in row:
            return row[key]
    return None


def _missing_equity_fields(rows: list[dict[str, str]]) -> set[str]:
    missing: set[str] = set()
    for row in rows:
        label = row.get("Multiple") or row.get("Metric")
        if label is not None and row.get("Value") == _EM_DASH:
            missing.add(label)
    return missing


def _assert_warnings_explain_missing(
    missing: set[str], data_warnings: list[str], page_path: str
) -> None:
    for field in sorted(missing):
        token = _EQUITY_FIELD_WARNING_TOKENS.get(field, field)
        if not any(token in warning for warning in data_warnings):
            logger.error(
                "%s: '%s' is not shown but no data_warnings entry explains it; data_warnings=%r",
                page_path,
                field,
                data_warnings,
            )
            raise SourcePageIntegrityError(
                f"{page_path}: '{field}' is not shown but no data_warnings entry "
                "explains it -- upstream render regression or a parsing bug here."
            )
