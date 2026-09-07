"""The citation guard: two mechanical checks over a ResearchAnswer's claims.

Every retrieved page is already numeric-fidelity-verified output of its own
system, so the residual risk is in *synthesis* -- a real figure attributed to the
wrong page, an uncomputed cross-page or cross-date relationship, a number that
exists nowhere.

Check 1 -- per-citation numeric fidelity. Every load-bearing numeral in a claim
must (a) carry a citation and (b) appear, exact unit and trailing-zero-normalised,
in the figure set of *that claim's own cited page*, not the union of every
retrieved page (a union check passes misattribution -- the number is real
*somewhere*). A ``"none"`` citation asserts the claim has zero figures.

Check 2 -- comparison / inference constraint. (2a) An equity or comps claim that
names another retrieved page's subject but not the cited page's read the figure
from one page and pinned it to another: fail. (2b) A relational or "change"
clause ("rose", "above", "cumulatively") is backed only by a figure the cited
page itself publishes as a relational quantity -- a macro note's own 1D/1W/1M
delta or curve slope; nothing for equity and comps, which have no time dimension.
Cross-date phrasings ("since 2026-08-28", "the prior week") are never backed.

Known limits. (1) No intra-page metric attribution (shared with the sibling
numeric-fidelity guards): a fabricated "+12bp" cumulative move still traces on
check 1 if some unrelated metric on a retrieved page happens to have moved 12bp
-- the block then comes from check 2, which is why cross-date claims are rejected
structurally, not by number. (2) No unit conversion: a claim that re-expresses a
cited figure in a different unit than its source used over-blocks (recoverable
via retry) -- see ``figures`` for why that is left as-is.

Dual mode: ``fail_fast`` returns the first violation (feed it back, retry once);
``collect_all`` returns every violation. Each is structured -- which claim, which
numeral, and a ``detail`` string naming where the figure really lives and what
the cited page reports -- so ``render_retry_feedback`` turns the list straight
into the retry turn.
"""

import re
from collections import OrderedDict
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from apps.research_agent.figures import (
    FigureUnit,
    extract_figures,
    figure_set,
    page_figures,
    relational_allowlist,
)
from apps.research_agent.models import NO_CITATION, Claim, ResearchAnswer, SourcePage

ViolationKind = Literal[
    "uncited_figure",
    "unknown_citation",
    "figure_not_in_citation",
    "subject_mismatch",
    "unbacked_relation",
]

GuardMode = Literal["fail_fast", "collect_all"]

_SUBJECT_STORE_SYSTEMS = ("equity_snapshot", "comps")
_DATE_SCOPE_OUT_SYSTEMS = ("equity_snapshot", "macro_note")

# Clause boundaries: comma, semicolon, en dash (U+2013), em dash (U+2014).
_CLAUSE_SPLIT_RE = re.compile("[,;\u2013\u2014]")

_RELATIONAL_CUE_RE = re.compile(
    r"\b(?:above|below|higher|lower|exceeds?|exceeded|versus|vs|compared|"
    r"cumulative(?:ly)?|consecutive(?:ly)?|widened|narrowed|rose|risen|fell|fallen|"
    r"gain(?:ed|ing)?|declin(?:ed|ing)|climbed|dropped|increased|decreased|"
    r"add(?:ed|ing)|outpaced|steeper|flatter|since|prior|running|streak)\b",
    re.IGNORECASE,
)

# Phrasings that imply a window the single cited note does not itself publish as a
# labelled delta -> never backed, even if a same-magnitude delta happens to exist.
_CROSS_DATE_RE = re.compile(
    r"\b(?:cumulative(?:ly)?|consecutive(?:ly)?|since|prior\s+(?:week|day|session|month)|"
    r"week[-\s]on[-\s]week|month[-\s]to[-\s]date|year[-\s]to[-\s]date|running|"
    r"in\s+a\s+row|streak|so\s+far)\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)")

# Trailing tokens stripped from a subject name to get a loose stem that still
# substring-matches prose ("Apple Inc." -> "apple" matches "Apple's").
# fmt: off
_CORP_SUFFIXES = frozenset({
    "inc", "corp", "corporation", "co", "ltd", "limited", "plc", "llc",
    "lp", "nv", "sa", "ag", "se", "group", "holdings", "company", "the",
})
# fmt: on

_UNIT_WORD: dict[str, str] = {
    "percent": "percentages",
    "multiple": "multiples",
    "basis_points": "basis-point figures",
    "unspecified": "figures",
}


class CitationViolation(BaseModel):
    """One failure found by the citation guard."""

    model_config = ConfigDict(frozen=True)

    claim_index: int
    claim_text: str
    citation: str
    kind: ViolationKind
    figure: str | None
    detail: str


class CitationGuardError(RuntimeError):
    """Raised by ``enforce_citations`` when any claim fails the citation guard."""


def check_citations(
    answer: ResearchAnswer,
    retrieved: Mapping[str, SourcePage],
    *,
    mode: GuardMode,
) -> list[CitationViolation]:
    """Run both checks over `answer`'s claims against the `retrieved` pages.

    Returns an empty list when every load-bearing numeral is cited and traces to
    its own cited page, no claim names a foreign subject, and no relational claim
    rests on an unpublished number. ``fail_fast`` stops at the first failing claim
    and returns just its first violation; ``collect_all`` returns every violation.
    """
    fig_sets = {doc_id: figure_set(page) for doc_id, page in retrieved.items()}
    violations: list[CitationViolation] = []
    for index, claim in enumerate(answer.claims):
        found = _fidelity_violations(index, claim, retrieved, fig_sets)
        found += _relation_violations(index, claim, retrieved)
        if mode == "fail_fast" and found:
            return found[:1]
        violations.extend(found)
    return violations


def enforce_citations(answer: ResearchAnswer, retrieved: Mapping[str, SourcePage]) -> None:
    """Raise ``CitationGuardError`` if `answer` has any citation-guard violation."""
    violations = check_citations(answer, retrieved, mode="collect_all")
    if not violations:
        return
    details = "; ".join(f"claim {v.claim_index + 1}: {v.detail}" for v in violations)
    raise CitationGuardError(f"Citation guard failed -- {details}")


def render_retry_feedback(
    violations: list[CitationViolation], retrieved: Mapping[str, SourcePage]
) -> str:
    """Turn a violation list into the single user turn sent back for the one retry.

    Grouped by claim, each failure rendered as its own ``detail`` line, with a
    closing list of the doc_ids that may be cited. Empty input -> empty string.
    """
    if not violations:
        return ""
    by_claim: OrderedDict[int, tuple[str, list[CitationViolation]]] = OrderedDict()
    for violation in violations:
        _, bucket = by_claim.setdefault(violation.claim_index, (violation.claim_text, []))
        bucket.append(violation)

    lines = [
        "The previous answer failed citation verification. Correct only the claims",
        "listed below, then return the complete answer again in the same structure;",
        "leave every other claim exactly as it was.",
        "",
    ]
    for index, (text, bucket) in by_claim.items():
        lines.append(f'Claim {index + 1}: "{text}"')
        lines.extend(f"  - {v.detail}" for v in bucket)
        lines.append("")
    lines.append(f"Cite only these sources: {', '.join(sorted(retrieved))}.")
    return "\n".join(lines)


def _fidelity_violations(
    index: int,
    claim: Claim,
    retrieved: Mapping[str, SourcePage],
    fig_sets: Mapping[str, set[tuple[float, FigureUnit]]],
) -> list[CitationViolation]:
    figures = extract_figures(claim.text)

    if claim.citation == NO_CITATION:
        return [
            _violation(
                index,
                claim,
                "uncited_figure",
                figure.text,
                f'Claim {index + 1} carries the figure "{figure.text}" but cites nothing. '
                f'A claim whose citation is "{NO_CITATION}" must contain no figures; '
                f"attribute it to the source it came from, or drop it.",
            )
            for figure in figures
        ]

    if claim.citation not in retrieved:
        return [
            _violation(
                index,
                claim,
                "unknown_citation",
                None,
                f'Claim {index + 1} cites "{claim.citation}", which was not retrieved for '
                f"this question. Cite one of: {', '.join(sorted(retrieved))}.",
            )
        ]

    cited = retrieved[claim.citation]
    if cited.system in _DATE_SCOPE_OUT_SYSTEMS:
        figures = [f for f in figures if not _is_year_token(f.text, f.unit)]

    cited_keys = fig_sets[claim.citation]
    out: list[CitationViolation] = []
    for figure in figures:
        key = (round(figure.value, 9), figure.unit)
        if key in cited_keys:
            continue
        elsewhere = sorted(
            doc_id for doc_id, keys in fig_sets.items() if doc_id != claim.citation and key in keys
        )
        out.append(
            _violation(
                index,
                claim,
                "figure_not_in_citation",
                figure.text,
                _fidelity_detail(index, claim.citation, cited, figure.text, figure.unit, elsewhere),
            )
        )
    return out


def _fidelity_detail(
    index: int, citation: str, cited: SourcePage, figure: str, unit: str, elsewhere: list[str]
) -> str:
    if elsewhere:
        detail = (
            f'The figure "{figure}" is cited to {citation}, which does not contain it; '
            f"it appears in {', '.join(elsewhere)}. Cite the source the claim describes, "
            f"or split the sentence so each figure is cited to its own source."
        )
        reported = sorted({f.text for f in page_figures(cited) if f.unit == unit})
        if reported:
            detail += f" {citation} reports these {_UNIT_WORD[unit]}: {', '.join(reported)}."
        return detail
    return (
        f'The figure "{figure}" is cited to {citation}, but no retrieved source contains '
        f"it. A computed quantity (a difference, sum, average, or count) cannot be cited "
        f"because no source published it. State the relationship in words, or quote a "
        f"figure a source already gives."
    )


def _relation_violations(
    index: int, claim: Claim, retrieved: Mapping[str, SourcePage]
) -> list[CitationViolation]:
    if claim.citation == NO_CITATION or claim.citation not in retrieved:
        return []
    cited = retrieved[claim.citation]
    out: list[CitationViolation] = []

    if cited.system in _SUBJECT_STORE_SYSTEMS:
        text_lower = claim.text.lower()
        if not _mentions_subject(text_lower, cited):
            foreign = sorted(
                doc_id
                for doc_id, page in retrieved.items()
                if doc_id != claim.citation
                and page.system in _SUBJECT_STORE_SYSTEMS
                and _mentions_subject(text_lower, page)
            )
            if foreign:
                other = retrieved[foreign[0]]
                out.append(
                    _violation(
                        index,
                        claim,
                        "subject_mismatch",
                        None,
                        f"Claim {index + 1} describes {_subject_label(other)} (from "
                        f"{foreign[0]}) but cites {claim.citation}. Cite the page whose "
                        f"subject the claim is about.",
                    )
                )

    allow = relational_allowlist(cited)
    for clause in _clauses(claim.text):
        if not _RELATIONAL_CUE_RE.search(clause):
            continue
        cross_date = cited.system == "macro_note" and bool(
            _CROSS_DATE_RE.search(clause) or _ISO_DATE_RE.search(clause)
        )
        clause_keys = {(round(f.value, 9), f.unit) for f in extract_figures(clause)}
        if not cross_date and clause_keys & allow:
            continue
        out.append(
            _violation(
                index,
                claim,
                "unbacked_relation",
                None,
                _relation_detail(index, cited, clause.strip()),
            )
        )
    return out


def _relation_detail(index: int, cited: SourcePage, clause: str) -> str:
    if cited.system == "macro_note":
        return (
            f'Claim {index + 1} states a change or trend ("{clause}") that {cited.doc_id} '
            f"does not publish. A macro note backs a relational claim only by quoting that "
            f"metric's own 1D, 1W, or 1M delta verbatim; cross-date and multi-period trends "
            f"are not available."
        )
    thing = "Equity snapshots" if cited.system == "equity_snapshot" else "Comps tables"
    return (
        f'Claim {index + 1} asserts a change or comparison ("{clause}"); {thing} carry no '
        f"figures over time, so state only the level each source reports, each as its own claim."
    )


def _violation(
    index: int, claim: Claim, kind: ViolationKind, figure: str | None, detail: str
) -> CitationViolation:
    return CitationViolation(
        claim_index=index,
        claim_text=claim.text,
        citation=claim.citation,
        kind=kind,
        figure=figure,
        detail=detail,
    )


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]


def _mentions_subject(text_lower: str, page: SourcePage) -> bool:
    return any(stem in text_lower for stem in _subject_stems(page))


def _subject_label(page: SourcePage) -> str:
    return page.subject_terms[0] if page.subject_terms else page.doc_id


def _subject_stems(page: SourcePage) -> set[str]:
    stems: set[str] = set()
    for term in page.subject_terms:
        lowered = term.strip().lower()
        if not lowered:
            continue
        stems.add(lowered)
        parts = re.split(r"[\s,]+", lowered)
        while len(parts) > 1 and parts[-1].strip(".") in _CORP_SUFFIXES:
            parts = parts[:-1]
        stem = " ".join(parts).strip(" ,.")
        if len(stem) >= 3:
            stems.add(stem)
    return stems


def _is_year_token(text: str, unit: str) -> bool:
    return unit == "unspecified" and text.isdigit() and len(text) == 4 and 1900 <= int(text) <= 2099
