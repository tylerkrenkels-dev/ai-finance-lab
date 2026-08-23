"""Writes a rendered comparables table to disk and refreshes the comps index.

Two independently-testable functions, composed by a thin orchestrator -- the
same split as apps/macro_note/publish.py:

- write_table() renders and writes one table file. Refuses to overwrite an
  existing file for the same table_id unless overwrite=True is passed
  explicitly: these are hand-curated, permanent reference tables, so a silent
  overwrite on a rerun risks quietly replacing a published table with no
  signal to anyone. overwrite=True is the deliberate, auditable escape hatch
  for a genuine correction (e.g. a registry fix like the Svmantec comment).

- update_index() regenerates the managed entry list in comps_dir/index.md
  from the table files actually present in comps_dir, not by parsing and
  patching the index's own previous output -- the same "derived artifact =
  full regeneration from the filesystem" pattern as macro_note's
  update_index. Crucially, it derives every field (deal name, filing date,
  status, advisor, analysis label) from what render_table() actually wrote
  to disk -- front matter and the "## Source" section -- never from
  apps.comps.registry. If a published file were hand-edited, or a registry
  entry changed without republishing, the index reflects the file on disk,
  not the registry's current state.

One real difference from macro_note: notes are one-per-day, so a reverse-
chronological flat list is the only sensible order. Comps is six static
reference tables across five deals, and Norfolk Southern/Union Pacific has
two tables (one per advisor) from the same filing -- a flat list would
either separate them or need a fragile filename-prefix match. Instead,
entries are grouped by deal (parsed from each table's title, which render.py
always writes as `"{target} / {acquiror} — {analysis_label}"` -- everything
before the em dash is the group key), deal groups ordered by their most
recent table's filing date descending (mirroring macro_note's "most recent
first"), ties broken alphabetically by deal name, and tables within a deal
group ordered alphabetically by advisor for a deterministic Norfolk Southern
order. Pending deals get a bold **Pending** marker in the group heading,
echoing render.py's convention in the table body.

Only the text between two HTML-comment markers in index.md is ever rewritten,
so hand-authored prose above and below them is preserved untouched. If the
markers are missing, update_index raises rather than guessing where to
insert -- this is a hand-authored docs page, not a generated one.
"""

import re
from datetime import date
from pathlib import Path

from apps.comps.models import ComparableTransactionsTable, Deal
from apps.comps.render import render_table, table_filename

DEFAULT_DOCS_DIR = Path("docs")

_MARKER_START = "<!-- comps:start -->"
_MARKER_END = "<!-- comps:end -->"

_TITLE_RE = re.compile(r'^title: "(.+)"$', re.MULTILINE)
_DATE_RE = re.compile(r"^date: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
_STATUS_RE = re.compile(r'^status: "(.+)"$', re.MULTILINE)
_SOURCE_SECTION_RE = re.compile(r'^- \*\*Section:\*\* ".+" \((.+)\)$', re.MULTILINE)

# (deal_label, filed_date, status, advisor, analysis_label, filename)
_TableEntry = tuple[str, date, str, str, str, str]


def write_table(
    table: ComparableTransactionsTable, deal: Deal, comps_dir: Path, *, overwrite: bool = False
) -> Path:
    """Render `table`/`deal` and write to comps_dir/<table_filename(table)>.

    Raises FileExistsError if the target file already exists and overwrite is False.
    """
    comps_dir.mkdir(parents=True, exist_ok=True)
    path = comps_dir / table_filename(table)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. Published comp tables are hand-curated and "
            "permanent; pass overwrite=True to explicitly replace it."
        )
    path.write_text(render_table(table, deal))
    return path


def update_index(comps_dir: Path) -> None:
    """Regenerate the managed entry list in comps_dir/index.md from comps_dir's contents.

    Raises ValueError if index.md is missing the comps:start/comps:end markers.
    """
    index_path = comps_dir / "index.md"
    index_text = index_path.read_text()
    if _MARKER_START not in index_text or _MARKER_END not in index_text:
        raise ValueError(
            f"{index_path} is missing the managed region markers "
            f"({_MARKER_START!r} / {_MARKER_END!r}). Add them once, by hand, "
            "before this function can maintain the comps list."
        )

    list_text = _build_list_text(_scan_tables(comps_dir))

    before, _, rest = index_text.partition(_MARKER_START)
    _, _, after = rest.partition(_MARKER_END)
    index_path.write_text(f"{before}{_MARKER_START}\n{list_text}\n{_MARKER_END}{after}")


def publish_table(
    table: ComparableTransactionsTable,
    deal: Deal,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    overwrite: bool = False,
) -> Path:
    """Write the table and refresh the index. Returns the path to the written file."""
    comps_dir = docs_dir / "comps"
    path = write_table(table, deal, comps_dir, overwrite=overwrite)
    update_index(comps_dir)
    return path


def _scan_tables(comps_dir: Path) -> list[_TableEntry]:
    entries: list[_TableEntry] = []
    for path in comps_dir.iterdir():
        if path.name == "index.md" or path.suffix != ".md":
            continue
        entries.append(_parse_table_file(path))
    return entries


def _parse_table_file(path: Path) -> _TableEntry:
    text = path.read_text()

    title_match = _TITLE_RE.search(text)
    date_match = _DATE_RE.search(text)
    status_match = _STATUS_RE.search(text)
    source_match = _SOURCE_SECTION_RE.search(text)
    if not (title_match and date_match and status_match and source_match):
        raise ValueError(f"{path} is missing an expected front matter or Source field")

    deal_label, _, analysis_label = title_match.group(1).rpartition(" — ")
    filed_date = date.fromisoformat(date_match.group(1))
    status = status_match.group(1)
    advisor = source_match.group(1)
    return (deal_label, filed_date, status, advisor, analysis_label, path.name)


def _build_list_text(entries: list[_TableEntry]) -> str:
    groups: dict[str, list[_TableEntry]] = {}
    for entry in entries:
        groups.setdefault(entry[0], []).append(entry)

    ordered_labels = sorted(groups)
    ordered_labels.sort(key=lambda label: max(entry[1] for entry in groups[label]), reverse=True)

    blocks = []
    for label in ordered_labels:
        group = sorted(groups[label], key=lambda entry: entry[3])
        status = group[0][2]
        heading = f"### {label}" + (" — **Pending**" if status == "pending" else "")
        entry_lines = [
            f"- [{advisor} — {analysis_label}]({filename})"
            for _, _, _, advisor, analysis_label, filename in group
        ]
        blocks.append(heading + "\n\n" + "\n".join(entry_lines))
    return "\n\n".join(blocks)
