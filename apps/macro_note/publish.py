"""Writes a rendered note to disk and refreshes the notes index.

Two independently-testable functions, composed by a thin orchestrator:

- write_note() renders and writes one dated note file. Refuses to overwrite
  an existing note for the same date unless overwrite=True is passed
  explicitly -- docs/notes/index.md itself states published notes are
  "dated and permanent"; a silent-overwrite default risks an orchestration
  retry quietly replacing a previously-published note with no signal to
  anyone. overwrite=True is the deliberate, auditable escape hatch for a
  genuine correction.

- update_index() regenerates the managed entry list in docs/notes/index.md
  from the note files actually present in notes_dir, not by parsing and
  patching the index's own previous output. This mirrors store.py's own
  idempotency pattern: the Parquet export there is a full regeneration from
  the authoritative DuckDB table on every write, not an incremental patch --
  here, the filesystem (which note files actually exist) is the authoritative
  source, and the index is a pure function of it. Running update_index twice
  against the same files on disk produces byte-identical output both times,
  and a note file added or removed by hand is reflected on the next call
  with no separate bookkeeping to keep in sync.

Only the text between two HTML-comment markers in index.md is ever rewritten,
so hand-authored prose above and below them is preserved untouched. If the
markers are missing, update_index raises rather than guessing where to
insert -- this is a hand-authored docs page, not a generated one.
"""

import re
from datetime import date
from pathlib import Path

from apps.macro_note.models import NoteFacts, NoteNarrative
from apps.macro_note.render import note_filename, render_note

DEFAULT_DOCS_DIR = Path("docs")

_MARKER_START = "<!-- notes:start -->"
_MARKER_END = "<!-- notes:end -->"

_NOTE_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_HEADLINE_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def write_note(
    facts: NoteFacts, narrative: NoteNarrative, notes_dir: Path, *, overwrite: bool = False
) -> Path:
    """Render `facts`/`narrative` and write to notes_dir/<note_filename(...)>.

    Raises FileExistsError if the target file already exists and overwrite is False.
    """
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / note_filename(facts.note_date)
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. Published notes are dated and permanent; "
            "pass overwrite=True to explicitly replace it."
        )
    path.write_text(render_note(facts, narrative))
    return path


def update_index(notes_dir: Path) -> None:
    """Regenerate the managed entry list in notes_dir/index.md from notes_dir's contents.

    Raises ValueError if index.md is missing the notes:start/notes:end markers.
    """
    index_path = notes_dir / "index.md"
    index_text = index_path.read_text()
    if _MARKER_START not in index_text or _MARKER_END not in index_text:
        raise ValueError(
            f"{index_path} is missing the managed region markers "
            f"({_MARKER_START!r} / {_MARKER_END!r}). Add them once, by hand, "
            "before this function can maintain the note list."
        )

    entries = _scan_notes(notes_dir)
    list_text = "\n".join(
        f"- [{note_date.isoformat()} — {headline}]({filename})"
        for note_date, headline, filename in entries
    )

    before, _, rest = index_text.partition(_MARKER_START)
    _, _, after = rest.partition(_MARKER_END)
    index_path.write_text(f"{before}{_MARKER_START}\n{list_text}\n{_MARKER_END}{after}")


def publish_note(
    facts: NoteFacts,
    narrative: NoteNarrative,
    docs_dir: Path = DEFAULT_DOCS_DIR,
    *,
    overwrite: bool = False,
) -> Path:
    """Write the note and refresh the index. Returns the path to the written note."""
    notes_dir = docs_dir / "notes"
    path = write_note(facts, narrative, notes_dir, overwrite=overwrite)
    update_index(notes_dir)
    return path


def _scan_notes(notes_dir: Path) -> list[tuple[date, str, str]]:
    entries: list[tuple[date, str, str]] = []
    for path in notes_dir.iterdir():
        if not _NOTE_FILENAME_RE.match(path.name):
            continue
        note_date = date.fromisoformat(path.stem)
        headline_match = _HEADLINE_RE.search(path.read_text())
        if headline_match is None:
            raise ValueError(f"{path} has no top-level heading to use as its index entry")
        entries.append((note_date, headline_match.group(1), path.name))
    entries.sort(key=lambda entry: entry[0], reverse=True)
    return entries
