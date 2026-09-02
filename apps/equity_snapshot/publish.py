"""Writes a rendered equity snapshot to disk and refreshes the snapshots index.

Two independently-testable functions, composed by a thin orchestrator -- the
same write / regenerate-index / thin-orchestrator split as
apps/macro_note/publish.py and apps/comps/publish.py. Two policy decisions
here are deliberately NOT inherited from either sibling, because a snapshot is
a genuinely different kind of artifact:

- write_snapshot() overwrites an existing page for the same ticker BY DEFAULT.
  macro_note and comps both refuse-by-default: a dated note and a curated comp
  table are permanent records, so a silent clobber on a cron retry would
  destroy a published artifact with no signal. That premise does not hold
  here. snapshot_filename() carries no date -- there is exactly one file per
  ticker, forever, and it is a *live* view that is meant to be replaced as
  prices move, not accumulated. The only real caller is a scheduled run that
  re-publishes the whole fixed watchlist every time; with overwrite=False it
  would have to pass overwrite=True on every call forever, so a
  refuse-by-default would protect nothing and be pure ceremony. The parameter
  is kept (overwrite=False lets a caller opt into "fail if the file is already
  there"), only the default is flipped.

- update_index() builds a FLAT list of the fixed ticker set, ordered
  alphabetically by ticker. Not macro_note's dated reverse-chronological
  archive (nothing accumulates -- it is always the same 3-5 rows) and not
  comps' grouped reference set (tickers have no logical grouping key). A run
  refreshes every ticker at roughly the same moment, so ordering by as_of
  would reshuffle the list on each publish based on which exchange's quote was
  a few minutes fresher -- churn with no meaning. Alphabetical by ticker is
  stable and matches how a watchlist reads.

Each index row shows the company name and ticker as the link plus the as_of
date ("snapshot as of 2026-08-24"). The date is not decoration: for a live
artifact it is the one thing that tells a reader whether they are looking at
today's prices or last month's, and without it the index gives no way to know.
It is per-row rather than a single index-level "as of" because the resilience
requirement means one ticker can fall back to a stale stored value while its
siblings are fresh. The model-authored headline is deliberately left off: for
a fixed 3-5 row list the company name already identifies each row, and the
headline changes every run as prices move -- churn on top of the meaningful
date churn. Leaving it off also keeps the index a purely Python-computed
artifact, every field parsed from front matter render_snapshot() itself wrote.

As in both siblings, update_index() derives every field from what
render_snapshot() actually wrote to disk (front matter), never from the
in-memory EquitySnapshot -- a hand-edited file is reflected as it is on disk.
Only the text between two HTML-comment markers in index.md is ever rewritten,
so hand-authored prose above and below them is preserved untouched. If the
markers are missing, update_index raises rather than guessing where to insert.

There is no numeric-fidelity guard call here, matching both siblings: the
guard is an orchestration concern for the (unwritten) main.py, which runs it
before calling publish_snapshot.
"""

import re
from datetime import date
from pathlib import Path

from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import EquitySnapshot
from apps.equity_snapshot.render import render_snapshot, snapshot_filename

DEFAULT_DOCS_DIR = Path("docs")

_MARKER_START = "<!-- equities:start -->"
_MARKER_END = "<!-- equities:end -->"

_TITLE_RE = re.compile(r'^title: "(.+)"$', re.MULTILINE)
_DATE_RE = re.compile(r"^date: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
_TICKER_RE = re.compile(r'^ticker: "(.+)"$', re.MULTILINE)

# render._page_title writes 'title: "{company} ({ticker}) — Equity Snapshot"'.
# The ticker used programmatically (the sort key) is read from the separate
# `ticker:` field, never parsed back out of this string -- the title is only
# ever the display label. This suffix is the one cosmetic bit to drop; if
# render's title format ever changes, a stale suffix shows up in the label
# rather than update_index raising mid-publish with the page already written.
_TITLE_SUFFIX = " — Equity Snapshot"

# (ticker, company_and_ticker_label, as_of_date, filename)
_IndexEntry = tuple[str, str, date, str]


def write_snapshot(
    snapshot: EquitySnapshot,
    narrative: TickerNarrative,
    equity_dir: Path,
    *,
    overwrite: bool = True,
) -> Path:
    """Render `snapshot`/`narrative` and write to equity_dir/<snapshot_filename(...)>.

    Overwrites an existing page for the same ticker by default -- a snapshot is
    a live view meant to be replaced as prices move, not a permanent record.
    Pass overwrite=False to raise FileExistsError instead when the file exists.
    """
    equity_dir.mkdir(parents=True, exist_ok=True)
    path = equity_dir / snapshot_filename(snapshot.ticker)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. Pass overwrite=True (the default) to replace "
            "the current snapshot for this ticker."
        )
    path.write_text(render_snapshot(snapshot, narrative))
    return path


def update_index(equity_dir: Path) -> None:
    """Regenerate the managed entry list in equity_dir/index.md from equity_dir's contents.

    Raises ValueError if index.md is missing the equities:start/equities:end markers.
    """
    index_path = equity_dir / "index.md"
    index_text = index_path.read_text()
    if _MARKER_START not in index_text or _MARKER_END not in index_text:
        raise ValueError(
            f"{index_path} is missing the managed region markers "
            f"({_MARKER_START!r} / {_MARKER_END!r}). Add them once, by hand, "
            "before this function can maintain the snapshot list."
        )

    entries = _scan_snapshots(equity_dir)
    list_text = "\n".join(
        f"- [{label}]({filename}) — snapshot as of {as_of.isoformat()}"
        for _, label, as_of, filename in entries
    )

    before, _, rest = index_text.partition(_MARKER_START)
    _, _, after = rest.partition(_MARKER_END)
    index_path.write_text(f"{before}{_MARKER_START}\n{list_text}\n{_MARKER_END}{after}")


def publish_snapshot(
    snapshot: EquitySnapshot,
    narrative: TickerNarrative,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    overwrite: bool = True,
) -> Path:
    """Write the snapshot and refresh the index. Returns the path to the written page."""
    equity_dir = docs_dir / "equities"
    path = write_snapshot(snapshot, narrative, equity_dir, overwrite=overwrite)
    update_index(equity_dir)
    return path


def _scan_snapshots(equity_dir: Path) -> list[_IndexEntry]:
    entries: list[_IndexEntry] = []
    for path in equity_dir.iterdir():
        if path.name == "index.md" or path.suffix != ".md":
            continue
        entries.append(_parse_snapshot_file(path))
    entries.sort(key=lambda entry: entry[0])
    return entries


def _parse_snapshot_file(path: Path) -> _IndexEntry:
    text = path.read_text()

    title_match = _TITLE_RE.search(text)
    date_match = _DATE_RE.search(text)
    ticker_match = _TICKER_RE.search(text)
    if not (title_match and date_match and ticker_match):
        raise ValueError(f"{path} is missing an expected front matter field (title/date/ticker)")

    label = title_match.group(1).removesuffix(_TITLE_SUFFIX)  # "BHP Group Limited (BHP.AX)"
    as_of = date.fromisoformat(date_match.group(1))
    ticker = ticker_match.group(1)
    return (ticker, label, as_of, path.name)
