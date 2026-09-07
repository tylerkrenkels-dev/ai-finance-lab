"""Tests for the Research Agent citation guard.

The load-bearing cases are the six hand-traced scenarios from the design session
(memory/research-agent-design-decisions.md), plus the three check-2 scenarios
that the six do not exercise. Every SourcePage is built for real through the
merged source-reading tools against the committed fixture pages -- nothing here
hand-rolls a SourcePage.

Case map:
  1. AAPL/MSFT ROE misattribution           -> figure_not_in_citation (check 1)
  2. comps cross-table misattribution        -> figure_not_in_citation (check 1)
  3. macro cross-date cumulative-change trap -> figure_not_in_citation x2 (check 1)
  4-6. three simpler passing claims          -> no violations
  7. AAPL/MSFT cross-page comparison (S4)    -> figure_not_in_citation + unbacked_relation
  8. macro stitched two-week direction       -> unbacked_relation only (check 2)
  9. cite value-source not subject           -> subject_mismatch (check 2a)
"""

from datetime import date
from pathlib import Path

import pytest

from apps.research_agent.figures import (
    extract_figures,
    figure_set,
    relational_allowlist,
)
from apps.research_agent.guards import (
    CitationGuardError,
    check_citations,
    enforce_citations,
    render_retry_feedback,
)
from apps.research_agent.models import NO_CITATION, Claim, ResearchAnswer
from apps.research_agent.sources import (
    read_comp_table,
    read_equity_snapshot,
    read_macro_note,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _pages(*pages):
    retrieved = {}
    for page in pages:
        assert page is not None
        retrieved[page.doc_id] = page
    return retrieved


def _aapl():
    return read_equity_snapshot("AAPL", docs_dir=_FIXTURES)


def _msft():
    return read_equity_snapshot("MSFT", docs_dir=_FIXTURES)


def _comp(table_id: str):
    return read_comp_table(table_id, docs_dir=_FIXTURES)


@pytest.fixture
def equities():
    return _pages(_aapl(), _msft())


@pytest.fixture
def notes():
    return _pages(
        read_macro_note(date(2026, 8, 28), docs_dir=_FIXTURES),
        read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES),
    )


@pytest.fixture
def comps():
    return _pages(_comp("splunk-cisco-qatalyst"), _comp("ansys-synopsys-qatalyst"))


# ------------------------------------------------------------------ figure grammar


class TestExtractFigures:
    def _pairs(self, text: str):
        return [(f.value, f.unit) for f in extract_figures(text)]

    def test_multiple_and_percent_units_are_distinguished(self) -> None:
        assert self._pairs("a trailing P/E of 37.33x and a forward P/E of 34.09x") == [
            (37.33, "multiple"),
            (34.09, "multiple"),
        ]
        assert self._pairs("return on equity of 34.04%") == [(34.04, "percent")]

    def test_basis_points_recognised_spaced_and_unspaced(self) -> None:
        assert self._pairs("adding 12bp to the yield") == [(12.0, "basis_points")]
        assert self._pairs("up 10.0 basis points on the week") == [(10.0, "basis_points")]

    def test_iso_date_contributes_no_numeral(self) -> None:
        assert self._pairs("since 2026-08-28 to reach 4.34%") == [(4.34, "percent")]

    def test_word_numbers_zero_to_twenty(self) -> None:
        assert self._pairs("has risen three consecutive sessions") == [(3.0, "unspecified")]

    def test_trailing_zero_normalisation(self) -> None:
        assert self._pairs("27.9x") == self._pairs("27.90x") == [(27.9, "multiple")]

    def test_thousands_separator_and_currency_wrapper(self) -> None:
        assert self._pairs("valued at USD 4.75 trillion") == [(4.75, "unspecified")]
        assert self._pairs("gold at 4,374.7002 USD/oz") == [(4374.7002, "unspecified")]

    def test_points_is_not_a_unit(self) -> None:
        assert self._pairs("sits 9.4 points above Microsoft's") == [(9.4, "unspecified")]


class TestFigureSet:
    def test_equity_figure_set_is_per_page(self) -> None:
        aapl = figure_set(_aapl())
        assert (148.75, "percent") in aapl
        assert (37.33, "multiple") in aapl
        assert (4.75, "unspecified") in aapl
        # Microsoft's ROE must not be in Apple's figure set (this is what makes
        # case 1 misattribution, not fabrication).
        assert (34.04, "percent") not in aapl

    def test_equity_trailing_zero_from_table_cell(self) -> None:
        msft = figure_set(_msft())
        assert (34.04, "percent") in msft
        assert (27.9, "multiple") in msft  # cell reads "27.90x"

    def test_comps_multiples_exact_unit_no_conflation(self) -> None:
        splunk = figure_set(_comp("splunk-cisco-qatalyst"))
        ansys = figure_set(_comp("ansys-synopsys-qatalyst"))
        assert (5.8, "multiple") in splunk  # New Relic NTM Revenue multiple
        assert (5.9, "multiple") in ansys  # Neustar NTM LFCF multiple
        assert (5.8, "multiple") not in ansys

    def test_comps_provenance_numbers_are_not_figures(self) -> None:
        ansys = figure_set(_comp("ansys-synopsys-qatalyst"))
        # CIK 1013462, and the "07/31/23"-style announcement raw strings, and
        # accession fragments must never enter the figure set.
        assert (1013462.0, "unspecified") not in ansys
        assert (23.0, "unspecified") not in ansys
        assert (31.0, "unspecified") not in ansys

    def test_comps_summary_stats_are_figures_even_without_row_multiples(self) -> None:
        footlocker = figure_set(_comp("footlocker-dicks-evercore"))
        assert (7.4, "multiple") in footlocker  # Mean
        assert (6.9, "multiple") in footlocker  # Median

    def test_comps_year_cell_is_in_scope(self) -> None:
        splunk = figure_set(_comp("splunk-cisco-qatalyst"))
        assert (2023.0, "unspecified") in splunk

    def test_macro_level_present_streak_and_fabrication_absent(self) -> None:
        macro = figure_set(read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES))
        assert (4.34, "percent") in macro  # a published level
        # "three consecutive sessions" is a count no note published.
        assert (3.0, "unspecified") not in macro
        assert (999.0, "percent") not in macro  # a fabricated level


class TestRelationalAllowlist:
    def test_macro_allows_own_published_deltas_and_slopes(self) -> None:
        allow = relational_allowlist(read_macro_note(date(2026, 9, 1), docs_dir=_FIXTURES))
        assert (10.0, "basis_points") in allow  # US 2-Year 1W delta
        assert (41.0, "basis_points") in allow  # US 2s10s slope
        # A level is not a delta: "rose to 4.34%" is not a backed relation.
        assert (4.34, "percent") not in allow

    def test_equity_and_comps_have_no_relational_figures(self) -> None:
        assert relational_allowlist(_aapl()) == set()
        assert relational_allowlist(_comp("splunk-cisco-qatalyst")) == set()


# ------------------------------------------------------------- the six + three


class TestCase1RoeMisattribution:
    def _answer(self):
        return ResearchAnswer(
            question="How do Apple and Microsoft compare on profitability and valuation?",
            claims=[
                Claim(
                    text=(
                        "Apple's return on equity of 34.04% reflects highly "
                        "efficient capital deployment."
                    ),
                    citation="equity_snapshot/AAPL",
                )
            ],
        )

    def test_blocks_with_a_single_misattribution_violation(self, equities) -> None:
        violations = check_citations(self._answer(), equities, mode="collect_all")
        assert len(violations) == 1
        violation = violations[0]
        assert violation.claim_index == 0
        assert violation.kind == "figure_not_in_citation"
        assert violation.figure == "34.04%"

    def test_detail_names_the_page_the_figure_really_lives_on(self, equities) -> None:
        violation = check_citations(self._answer(), equities, mode="collect_all")[0]
        assert "equity_snapshot/MSFT" in violation.detail
        # And it tells the model what AAPL actually reports.
        assert "148.75%" in violation.detail

    def test_global_union_would_have_passed_it(self, equities) -> None:
        # 34.04% *is* a real retrieved figure -- just not on the cited page.
        assert (34.04, "percent") in figure_set(equities["equity_snapshot/MSFT"])


class TestCase2CompsCrossTableMisattribution:
    def test_blocks_new_relic_multiple_tagged_to_the_wrong_table(self, comps) -> None:
        answer = ResearchAnswer(
            question="What NTM revenue multiple did New Relic trade at?",
            claims=[
                Claim(
                    text="New Relic, Inc. traded at an NTM revenue multiple of 5.8x.",
                    citation="comps/ansys-synopsys-qatalyst",
                )
            ],
        )
        violations = check_citations(answer, comps, mode="collect_all")
        assert [(v.kind, v.figure) for v in violations] == [("figure_not_in_citation", "5.8x")]
        assert "comps/splunk-cisco-qatalyst" in violations[0].detail


class TestCase3MacroCrossDateCumulativeChange:
    def test_blocks_the_cross_date_cumulative_change_claim(self, notes) -> None:
        answer = ResearchAnswer(
            question="How has the US 2-year yield moved this week?",
            claims=[
                Claim(
                    text=(
                        "The US 2-year yield has risen three consecutive sessions, "
                        "adding 12bp since 2026-08-28 to reach 4.34%."
                    ),
                    citation="macro_note/2026-09-01",
                )
            ],
        )
        violations = check_citations(answer, notes, mode="collect_all")
        assert violations  # the claim is blocked
        # The streak count is a computed number that no note published.
        fabricated = next(v for v in violations if v.figure == "three")
        assert fabricated.kind == "figure_not_in_citation"
        assert "no retrieved source" in fabricated.detail
        # The "12bp since 2026-08-28" cumulative move is caught as a cross-date
        # relation even though 12bp coincidentally traces to an unrelated metric.
        assert any(v.kind == "unbacked_relation" for v in violations)
        # 4.34% is genuinely on the cited page -- it must never be flagged.
        assert not any(v.figure == "4.34%" for v in violations)


class TestCases456SimpleClaimsPass:
    def test_three_single_subject_claims_pass_both_modes(self, equities) -> None:
        answer = ResearchAnswer(
            question="How do Apple and Microsoft compare on profitability and valuation?",
            claims=[
                Claim(
                    text=(
                        "Apple Inc. trades at a trailing price-to-earnings ratio of "
                        "37.33x and a forward P/E of 34.09x."
                    ),
                    citation="equity_snapshot/AAPL",
                ),
                Claim(
                    text=(
                        "Microsoft Corporation posts a gross margin of 67.94% and an "
                        "operating margin of 45.11%."
                    ),
                    citation="equity_snapshot/MSFT",
                ),
                Claim(
                    text=(
                        "Apple's return on equity of 148.75% indicates highly "
                        "efficient capital deployment."
                    ),
                    citation="equity_snapshot/AAPL",
                ),
            ],
        )
        assert check_citations(answer, equities, mode="collect_all") == []
        assert check_citations(answer, equities, mode="fail_fast") == []
        enforce_citations(answer, equities)  # does not raise


class TestCase7CrossPageComparison:
    def test_blocks_on_orphan_numeral_and_empty_relational_allowlist(self, equities) -> None:
        answer = ResearchAnswer(
            question="How do Apple and Microsoft compare on profitability?",
            claims=[
                Claim(
                    text="Apple's return on equity sits 9.4 points above Microsoft's.",
                    citation="equity_snapshot/AAPL",
                )
            ],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        kinds = {v.kind for v in violations}
        assert "figure_not_in_citation" in kinds
        assert "unbacked_relation" in kinds
        assert any(v.figure == "9.4" for v in violations)


class TestCase8StitchedTwoWeekDirection:
    def test_numeric_fidelity_passes_but_relation_is_unbacked(self, notes) -> None:
        answer = ResearchAnswer(
            question="How has the US 2-year yield moved?",
            claims=[
                Claim(
                    text=(
                        "The US 2-year yield rose 10.0bp over the week to 4.34%, "
                        "having also gained the prior week."
                    ),
                    citation="macro_note/2026-09-01",
                )
            ],
        )
        violations = check_citations(answer, notes, mode="collect_all")
        assert [v.kind for v in violations] == ["unbacked_relation"]
        assert "gained the prior week" in violations[0].detail


class TestCase9CiteValueSourceNotSubject:
    def test_blocks_when_claim_subject_is_a_different_retrieved_page(self, equities) -> None:
        answer = ResearchAnswer(
            question="What is Apple's return on equity?",
            claims=[
                Claim(
                    text="Apple's return on equity is 34.04%.",
                    citation="equity_snapshot/MSFT",
                )
            ],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        assert [v.kind for v in violations] == ["subject_mismatch"]
        assert "equity_snapshot/AAPL" in violations[0].detail


class TestCompsClaimPasses:
    def test_year_and_multiple_both_trace_to_the_cited_table(self, comps) -> None:
        # A comps year is in scope for the guard (unlike equity/macro front-matter
        # dates); both the year and the multiple must trace to the one cited table.
        answer = ResearchAnswer(
            question="What did New Relic trade at?",
            claims=[
                Claim(
                    text=(
                        "In 2023, New Relic, Inc. changed hands at an NTM revenue multiple of 5.8x."
                    ),
                    citation="comps/splunk-cisco-qatalyst",
                )
            ],
        )
        assert check_citations(answer, comps, mode="collect_all") == []


# --------------------------------------------------------------- guard mechanics


class TestNoCitationSentinel:
    def test_connective_prose_with_no_figure_passes(self, equities) -> None:
        answer = ResearchAnswer(
            question="q",
            claims=[
                Claim(
                    text="The two technology leaders present distinct profiles.",
                    citation=NO_CITATION,
                )
            ],
        )
        assert check_citations(answer, equities, mode="collect_all") == []

    def test_a_figure_in_an_uncited_claim_is_blocked(self, equities) -> None:
        answer = ResearchAnswer(
            question="q",
            claims=[
                Claim(
                    text="Together they trade at a combined 65.71x.",
                    citation=NO_CITATION,
                )
            ],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        assert [v.kind for v in violations] == ["uncited_figure"]
        assert violations[0].figure == "65.71x"


class TestUnknownCitation:
    def test_citing_a_page_that_was_not_retrieved_is_blocked(self, equities) -> None:
        answer = ResearchAnswer(
            question="q",
            claims=[Claim(text="Apple trades at 37.33x.", citation="equity_snapshot/GOOG")],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        assert [v.kind for v in violations] == ["unknown_citation"]


class TestFabricatedFigureIsBlocked:
    """CLAUDE.md section 6: the guard has a test feeding it a fabricated figure."""

    def test_invented_percentage_is_blocked_and_enforce_raises(self, equities) -> None:
        answer = ResearchAnswer(
            question="What is Apple's return on equity?",
            claims=[
                Claim(
                    text="Apple's return on equity of 312.50% is exceptional.",
                    citation="equity_snapshot/AAPL",
                )
            ],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        assert any(v.kind == "figure_not_in_citation" and v.figure == "312.50%" for v in violations)
        with pytest.raises(CitationGuardError):
            enforce_citations(answer, equities)


class TestModes:
    def test_fail_fast_stops_at_first_collect_all_returns_every(self, notes) -> None:
        answer = ResearchAnswer(
            question="q",
            claims=[
                Claim(
                    text="The 2-year yield added 12bp cumulatively to 4.34%.",
                    citation="macro_note/2026-09-01",
                ),
                Claim(
                    text="Gold fell 9.99% to 4,374.7002 USD/oz.",
                    citation="macro_note/2026-09-01",
                ),
            ],
        )
        fail_fast = check_citations(answer, notes, mode="fail_fast")
        collect_all = check_citations(answer, notes, mode="collect_all")
        assert len(fail_fast) == 1
        assert len(collect_all) > len(fail_fast)
        assert fail_fast[0].claim_index == 0


class TestRenderRetryFeedback:
    def test_empty_violations_render_to_empty_string(self) -> None:
        assert render_retry_feedback([], {}) == ""

    def test_feedback_quotes_claims_names_targets_and_lists_sources(self, equities) -> None:
        answer = ResearchAnswer(
            question="How do Apple and Microsoft compare on profitability?",
            claims=[
                Claim(
                    text=(
                        "Apple's return on equity of 34.04% reflects highly "
                        "efficient capital deployment."
                    ),
                    citation="equity_snapshot/AAPL",
                ),
                Claim(
                    text="Apple's return on equity sits 9.4 points above Microsoft's.",
                    citation="equity_snapshot/AAPL",
                ),
            ],
        )
        violations = check_citations(answer, equities, mode="collect_all")
        text = render_retry_feedback(violations, equities)
        assert "Claim 1" in text and "Claim 2" in text
        assert "34.04%" in text
        assert "equity_snapshot/MSFT" in text  # where 34.04% really lives
        assert "148.75%" in text  # what AAPL actually reports
        assert "9.4" in text
        assert text.strip().endswith(
            "Cite only these sources: equity_snapshot/AAPL, equity_snapshot/MSFT."
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
