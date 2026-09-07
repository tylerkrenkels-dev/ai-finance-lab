"""``list_available_sources``: the single call that says what the agent can read.

Discovery is deliberately separate from retrieval (``sources.read_*``): it answers
"what exists" cheaply, reading only front matter, so the agent can choose a page
without opening every one. Comps entries come from the registry but are listed
only when their published page exists under ``docs_dir`` -- consistent with
``read_comp_table`` returning None in the same case.
"""

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from apps.comps import registry
from apps.research_agent.markdown_parsing import parse_front_matter
from apps.research_agent.models import SourceSystem
from apps.research_agent.sources import DEFAULT_DOCS_DIR

_NOTE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class SourceRef(BaseModel):
    """One readable source, with enough metadata to choose it without opening the page."""

    model_config = ConfigDict(frozen=True)

    system: SourceSystem
    doc_id: str
    key: str
    """The native argument for the matching ``read_*`` function: an ISO date, a
    ticker, or a table_id."""
    label: str
    as_of: date


def list_available_sources(docs_dir: Path = DEFAULT_DOCS_DIR) -> list[SourceRef]:
    """Every readable source across the three systems, grouped by system.

    Macro notes newest-first; equity snapshots by ticker; comps tables (only those
    with a published page) newest-filing-first.
    """
    return [*_macro_refs(docs_dir), *_equity_refs(docs_dir), *_comp_refs(docs_dir)]


def _macro_refs(docs_dir: Path) -> list[SourceRef]:
    notes_dir = docs_dir / "notes"
    if not notes_dir.is_dir():
        return []
    refs: list[SourceRef] = []
    for path in notes_dir.glob("*.md"):
        if not _NOTE_NAME_RE.match(path.name):
            continue
        description = parse_front_matter(path.read_text()).get("description", "")
        refs.append(
            SourceRef(
                system="macro_note",
                doc_id=f"macro_note/{path.stem}",
                key=path.stem,
                label=f"{path.stem} — {description}".rstrip(" —"),
                as_of=date.fromisoformat(path.stem),
            )
        )
    return sorted(refs, key=lambda ref: ref.as_of, reverse=True)


def _equity_refs(docs_dir: Path) -> list[SourceRef]:
    equities_dir = docs_dir / "equities"
    if not equities_dir.is_dir():
        return []
    refs: list[SourceRef] = []
    for path in sorted(equities_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        front_matter = parse_front_matter(path.read_text())
        ticker = front_matter.get("ticker", path.stem.upper())
        company = front_matter.get("title", "").split(" (")[0]
        refs.append(
            SourceRef(
                system="equity_snapshot",
                doc_id=f"equity_snapshot/{ticker}",
                key=ticker,
                label=f"{company} ({ticker})".strip(),
                as_of=date.fromisoformat(front_matter["date"]),
            )
        )
    return refs


def _comp_refs(docs_dir: Path) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for table in registry.TABLES:
        if not (docs_dir / "comps" / f"{table.table_id}.md").is_file():
            continue
        deal = next(d for d in registry.DEALS if d.deal_id == table.deal_id)
        refs.append(
            SourceRef(
                system="comps",
                doc_id=f"comps/{table.table_id}",
                key=table.table_id,
                label=f"{deal.target_name} / {deal.acquiror_name} — {table.advisor}",
                as_of=table.source.filed_date,
            )
        )
    return sorted(refs, key=lambda ref: (ref.as_of, ref.doc_id), reverse=True)
