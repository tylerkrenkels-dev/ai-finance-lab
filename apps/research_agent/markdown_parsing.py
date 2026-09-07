"""Small, pure parsers for the markdown the three source systems publish.

New, reusable work: the three systems' own ``update_index`` functions parse only
front matter, never table bodies, so there was nothing to reuse. These functions
are deliberately minimal -- flat front matter, GitHub-style pipe tables, ``## ``/
``### `` section headings, ``- `` bullet lists -- because that is the entire
surface the source renderers actually emit. They do not attempt to be a general
markdown parser.

Kept inside ``apps/research_agent`` rather than promoted to ``core/``: only this
app needs them (CLAUDE.md's rule of three). Module named ``markdown_parsing`` to
avoid shadowing the ``markdown`` PyPI package MkDocs pulls in.
"""

import re

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n*", re.DOTALL)
_H2_RE = re.compile(r"^## (?!#)(.+)$")
_H3_RE = re.compile(r"^### (.+)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


def parse_front_matter(text: str) -> dict[str, str]:
    """Parse a leading ``---`` ... ``---`` block of flat ``key: value`` lines.

    Surrounding double quotes are stripped from values. Values may themselves
    contain ``": "``; only the first occurrence splits key from value. Returns an
    empty dict if `text` has no front-matter block.
    """
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def strip_front_matter(text: str) -> str:
    """Return `text` with a leading ``---`` ... ``---`` block removed, if present."""
    return _FRONT_MATTER_RE.sub("", text, count=1)


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split `body` into ``(heading, section_body)`` pairs on ``## ``/``### `` headings.

    An ``### `` heading is qualified with its nearest preceding ``## `` heading as
    ``"<h2> / <h3>"``, so e.g. every category's ``### Metrics`` is distinguishable.
    Content before the first heading is not returned, and a heading whose body is
    empty (an ``## `` heading that only introduces child ``### `` blocks) is
    dropped -- it carries no structured content to extract.
    """
    sections: list[tuple[str, list[str]]] = []
    parent_h2: str | None = None
    for line in body.splitlines():
        h2 = _H2_RE.match(line)
        h3 = _H3_RE.match(line)
        if h2 is not None:
            parent_h2 = h2.group(1).strip()
            sections.append((parent_h2, []))
        elif h3 is not None:
            h3_text = h3.group(1).strip()
            heading = f"{parent_h2} / {h3_text}" if parent_h2 is not None else h3_text
            sections.append((heading, []))
        elif sections:
            sections[-1][1].append(line)
    pairs = [(heading, "\n".join(lines).strip()) for heading, lines in sections]
    return [(heading, body) for heading, body in pairs if body]


def parse_pipe_tables(section_body: str) -> list[list[dict[str, str]]]:
    """Every GitHub-style pipe table in `section_body`, as lists of row dicts.

    A table is a header row, a ``|---|---|`` separator row, then one dict per data
    row keyed by the (verbatim) header cells. Cells are stripped of surrounding
    whitespace but otherwise kept exactly as written, em-dashes included.
    """
    tables: list[list[dict[str, str]]] = []
    lines = section_body.splitlines()
    i = 0
    while i < len(lines):
        header = _split_row(lines[i])
        separator = _split_row(lines[i + 1]) if i + 1 < len(lines) else None
        if header is None or separator is None or not _is_separator(separator):
            i += 1
            continue
        rows: list[dict[str, str]] = []
        j = i + 2
        while j < len(lines):
            cells = _split_row(lines[j])
            if cells is None:
                break
            rows.append({header[k]: cells[k] for k in range(min(len(header), len(cells)))})
            j += 1
        tables.append(rows)
        i = j
    return tables


def parse_bullets(section_body: str) -> list[str]:
    """Every top-level ``- `` bullet line in `section_body`, marker stripped."""
    return [
        line.strip()[2:].strip()
        for line in section_body.splitlines()
        if line.strip().startswith("- ")
    ]


def _split_row(line: str) -> list[str] | None:
    """Split a ``| a | b |`` markdown row into stripped cells, or None if not a row."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell) for cell in cells)
