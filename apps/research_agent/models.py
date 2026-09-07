"""The SourcePage envelope: the uniform shape every source-reading tool returns.

The Research Agent reads from the three live systems through one interface. Two of
them (Macro Digest, Equity Snapshot) have no durable structured store, so their
SourcePage is parsed from the committed markdown a human reads on the site; the
third (M&A Comps) is built from the importable ``apps.comps.registry`` and only
borrows its ``raw_markdown`` from the published page. Regardless of origin, the
shape is identical so the citation guard and the agent treat all three the same.

Fields carry values verbatim -- the exact strings Python already formatted in the
source system ("4.34%", "37.33x", "USD 4.75 trillion"). Nothing here re-types a
figure to float, re-rounds, or re-derives it. ``sections`` holds only what the
source system's renderer emitted as structured content (tables, Python-rendered
bullet lists); the model-authored headline and narrative prose live only in
``raw_markdown``.

``data_warnings`` is a first-class field, not one ``Section`` among many, because
it is the single authoritative account of why a value is absent. For equity
snapshots, ``apps.equity_snapshot.payload`` guarantees a specific warning for
every ``None`` field; ``sources.read_equity_snapshot`` asserts that guarantee
holds and raises if it ever does not, rather than letting a downstream claim
re-derive "missing" from a rendered em-dash. Comps has no such concept and
carries ``[]`` -- expected, not a gap.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

SourceSystem = Literal["macro_note", "comps", "equity_snapshot"]

NO_CITATION = "none"
"""Sentinel ``Claim.citation`` value for pure connective prose that cites nothing.
The citation guard requires such a claim to contain no load-bearing figures, so a
number never rides in an uncited claim."""


class Section(BaseModel):
    """One named block of structured content from a source page.

    ``rows`` is a list of dicts keyed by the block's own column/field labels, kept
    verbatim. A markdown pipe table becomes one dict per data row keyed by its
    header cells; a Python-rendered bullet list of ``**Key:** value`` lines
    becomes one dict per bullet. Rows whose only non-empty cell is a label (every
    figure cell was a "not shown" em-dash) are dropped before construction, so no
    em-dash ever appears here.
    """

    model_config = ConfigDict(frozen=True)

    heading: str
    rows: list[dict[str, str]]


class SourcePage(BaseModel):
    """The complete, uniform payload a source-reading tool returns for one page."""

    model_config = ConfigDict(frozen=True)

    system: SourceSystem
    doc_id: str
    """Stable citation token, ``"<system>/<key>"`` -- e.g. ``"equity_snapshot/AAPL"``,
    ``"macro_note/2026-09-01"``, ``"comps/splunk-cisco-qatalyst"``. This is what the
    agent emits as a citation and what a reader sees."""

    page_path: str
    """Repo-relative path to the published page this citation resolves to, e.g.
    ``"docs/equities/aapl.md"``."""

    subject_terms: list[str]
    """Identifier strings for the page's subject, for the guard's subject-consistency
    check -- equity: company name + ticker; comps: deal parties + table_id. Empty for
    macro notes, which have no single subject."""

    as_of: date
    """The page's own as-of date: front-matter ``date`` for macro/equity, filing date
    for comps."""

    stale: bool | None
    """Macro notes carry a front-matter ``stale`` flag; ``None`` for comps/equity,
    where the concept does not apply as a page-level flag."""

    data_warnings: list[str]
    """Verbatim entries from the page's ``## Data Warnings`` section (macro, equity).
    ``[]`` for comps and for pages with no such section. The single authoritative
    account of why any value is absent."""

    sections: list[Section]
    raw_markdown: str


class Claim(BaseModel):
    """One assertion in a research answer, bound to exactly one source.

    ``citation`` is a ``SourcePage.doc_id`` or the ``NO_CITATION`` sentinel. One
    doc_id per claim is deliberate: it removes the union-of-citations loophole
    that lets a real figure from page A ride in a claim cited to page B. A claim
    that needs two sources is two claims. ``NO_CITATION`` is only for connective
    prose; the citation guard requires such a claim to carry no figures.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    citation: str


class ResearchAnswer(BaseModel):
    """The agent's answer: an ordered list of single-cited claims.

    The answer *is* this list -- rendering joins ``claim.text`` with ``[n]``
    markers and appends a references block mapping each cited doc_id to its
    published page. The citation guard consumes this plus the ``dict[doc_id,
    SourcePage]`` the agent accumulated while retrieving.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    claims: list[Claim]
