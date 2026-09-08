"""Turn a verified ``ResearchAnswer`` (or a refusal) into the text a human reads.

Pure, no LLM. ``render_answer`` runs only on claims that have already passed the
citation guard, so every ``citation`` here is either a ``doc_id`` present in
``retrieved`` or the ``NO_CITATION`` sentinel. Distinct cited sources are
numbered in first-appearance order; claims sharing a source share a marker; a
``NO_CITATION`` claim (connective prose, guaranteed figure-free by the guard)
carries no marker.
"""

from collections.abc import Iterable, Mapping

from apps.research_agent.models import NO_CITATION, ResearchAnswer, SourcePage


def render_answer(answer: ResearchAnswer, retrieved: Mapping[str, SourcePage]) -> str:
    """Join the claims into one paragraph with ``[n]`` markers, then a references block.

    Args:
        answer: the surviving claims, in order.
        retrieved: every page cited by a claim, keyed by ``doc_id``.

    Returns:
        The rendered answer. If no claim cites a source, just the paragraph.
    """
    order: list[str] = []
    for claim in answer.claims:
        if claim.citation != NO_CITATION and claim.citation not in order:
            order.append(claim.citation)

    sentences: list[str] = []
    for claim in answer.claims:
        if claim.citation == NO_CITATION:
            sentences.append(claim.text)
        else:
            sentences.append(f"{claim.text} [{order.index(claim.citation) + 1}]")
    body = " ".join(sentences)

    if not order:
        return body
    references = "\n".join(
        f"[{i + 1}] {doc_id} — {retrieved[doc_id].page_path}" for i, doc_id in enumerate(order)
    )
    return f"{body}\n\nReferences\n{references}"


def render_refusal(question: str, consulted: Iterable[str], reason: str) -> str:
    """The text shown when too little could be verified to answer.

    Names every source that was consulted, so the reader can see the ground that
    was covered even though no claim survived.
    """
    sources = ", ".join(sorted(consulted)) or "none"
    return (
        f"Unable to provide a verified answer to: {question}\n\n"
        f"{reason}\n\n"
        f"Sources consulted: {sources}"
    )
