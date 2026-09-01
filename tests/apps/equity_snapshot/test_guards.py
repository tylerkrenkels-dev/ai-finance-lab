"""Numeric fidelity guard tests for the equity snapshot system.

The copied core (extract_numerals and its helpers) is exhaustively covered by
tests/apps/macro_note/test_guards.py; this file's one extract_numerals test is
a thin regression check on the copy. Everything else exercises the parts that
differ: a flat EquitySnapshot payload, headline+summary only, market_cap /
market_cap_display, and percent-tagging on the margin/ROE fields.

Test data is the real BHP.AX / JPM fundamentals already hand-verified in
test_calculations.py and test_payload.py -- no JSON fixtures, since (unlike
macro_note) there is no reconstructed production incident to freeze.
"""

import pytest

from apps.equity_snapshot.guards import (
    NumericFidelityError,
    check_numeric_fidelity,
    extract_numerals,
    find_untraceable_numerals,
)
from apps.equity_snapshot.narrative import TickerNarrative
from apps.equity_snapshot.payload import build_equity_snapshot
from tests.apps.equity_snapshot.test_calculations import _BHP, _JPM

_BHP_SNAPSHOT = build_equity_snapshot(_BHP)
_JPM_SNAPSHOT = build_equity_snapshot(_JPM)


# --- 1. Faithful narrative traces clean ---


def test_faithful_bhp_narrative_is_fully_traceable() -> None:
    narrative = TickerNarrative(
        headline="BHP trades at a premium multiple with heavy-industry margins",
        summary=(
            "BHP Group Limited last traded at 67.1, with a market capitalization of "
            "AUD 340.88 billion. It trades on a trailing P/E of 24.76x and a forward "
            "P/E of 18.62x. Gross margin is 85.92%, operating margin 43.34%, profit "
            "margin 16.73%, and return on equity 24.0%."
        ),
    )

    assert find_untraceable_numerals(narrative, _BHP_SNAPSHOT) == []
    check_numeric_fidelity(narrative, _BHP_SNAPSHOT)  # must not raise


# --- 2. market_cap_display: the canonical scaled form traces; a different
#        rounding of the same figure does not (the guard-level proof that the
#        payload-side redesign holds under adversarial input) ---


def test_market_cap_display_scaled_form_traces_but_a_different_rounding_does_not() -> None:
    traces = TickerNarrative(
        headline="BHP valuation snapshot",
        summary="BHP Group Limited is valued at AUD 340.88 billion.",
    )
    assert find_untraceable_numerals(traces, _BHP_SNAPSHOT) == []

    fabricated = TickerNarrative(
        headline="BHP valuation snapshot",
        summary="BHP Group Limited is valued at approximately AUD 341 billion.",
    )
    untraceable = find_untraceable_numerals(fabricated, _BHP_SNAPSHOT)
    assert len(untraceable) == 1
    u = untraceable[0]
    assert (u.value, u.unit, u.source_field) == (341.0, "unspecified", "summary")
    with pytest.raises(NumericFidelityError):
        check_numeric_fidelity(fabricated, _BHP_SNAPSHOT)


# --- 3. The raw market_cap integer is itself a valid trace target ---


def test_raw_market_cap_integer_restatement_traces() -> None:
    narrative = TickerNarrative(
        headline="BHP market capitalization",
        summary="BHP Group Limited's market capitalization stands at 340,878,950,400.",
    )
    assert find_untraceable_numerals(narrative, _BHP_SNAPSHOT) == []


# --- 4. Deliberately fabricated figure is blocked (CLAUDE.md section 6) ---


def test_deliberately_fabricated_pe_is_blocked() -> None:
    fabricated = TickerNarrative(
        headline="BHP earnings multiple",
        summary="BHP Group Limited trades on a trailing P/E of 22.10x.",
    )
    untraceable = find_untraceable_numerals(fabricated, _BHP_SNAPSHOT)
    assert len(untraceable) == 1
    u = untraceable[0]
    assert (u.value, u.unit, u.source_field) == (22.1, "unspecified", "summary")
    with pytest.raises(NumericFidelityError):
        check_numeric_fidelity(fabricated, _BHP_SNAPSHOT)


# --- 5. A P/E value cannot be laundered into a margin by tagging it "%" ---


def test_pe_value_cannot_be_laundered_as_a_margin_percentage() -> None:
    # 24.76 is BHP's real trailing_pe (an unspecified/multiple candidate), NOT a
    # percent candidate -- the percent pool is {85.92, 43.34, 16.73, 24.0}.
    fabricated = TickerNarrative(
        headline="BHP profitability",
        summary="BHP Group Limited posts an operating margin of 24.76%.",
    )
    untraceable = find_untraceable_numerals(fabricated, _BHP_SNAPSHOT)
    assert len(untraceable) == 1
    u = untraceable[0]
    assert (u.value, u.unit, u.source_field) == (24.76, "percent", "summary")


# --- 6. Currency-bridging fabrication is blocked; the data_warning that names
#        the two currency codes contributes no numerals of its own ---


def test_currency_bridging_fabrication_is_blocked_and_warning_has_no_numerals() -> None:
    assert extract_numerals(_BHP_SNAPSHOT.data_warnings[0]) == []

    fabricated = TickerNarrative(
        headline="BHP enterprise value",
        summary=(
            "After bridging the AUD/USD gap, BHP Group Limited's implied EV/EBITDA is near 8.0x."
        ),
    )
    untraceable = find_untraceable_numerals(fabricated, _BHP_SNAPSHOT)
    assert len(untraceable) == 1
    u = untraceable[0]
    assert (u.value, u.unit, u.source_field) == (8.0, "unspecified", "summary")
    with pytest.raises(NumericFidelityError):
        check_numeric_fidelity(fabricated, _BHP_SNAPSHOT)


# --- 7. A computed difference between two real figures is a fabrication -- this
#        system carries no change/horizon figures, so every delta is invented ---


def test_fabricated_computed_difference_is_blocked_only_for_the_derived_number() -> None:
    fabricated = TickerNarrative(
        headline="BHP forward versus trailing",
        summary=(
            "BHP Group Limited's forward P/E of 18.62x sits 6.14 turns below its trailing 24.76x."
        ),
    )
    untraceable = find_untraceable_numerals(fabricated, _BHP_SNAPSHOT)
    assert len(untraceable) == 1
    u = untraceable[0]
    assert (u.value, u.unit, u.source_field) == (6.14, "unspecified", "summary")


# --- 8. Year and day-of-month from as_of are traceable (as_of is a datetime;
#        the month component contributes no numeral, as in macro_note) ---


def test_as_of_date_components_are_traceable() -> None:
    # BHP's as_of resolves to 2026-08-24.
    narrative = TickerNarrative(
        headline="BHP as of the quote date",
        summary="As of August 24, 2026, BHP Group Limited traded at 67.1.",
    )
    assert find_untraceable_numerals(narrative, _BHP_SNAPSHOT) == []


# --- 9. JPM: a None profitability field does not crash the guard; a faithful
#        JPM narrative traces; the sector-suppression warning has no numerals ---


def test_faithful_jpm_narrative_traces_with_none_gross_margin_and_no_crash() -> None:
    assert _JPM_SNAPSHOT.profitability.gross_margin_pct is None
    assert extract_numerals(_JPM_SNAPSHOT.data_warnings[0]) == []

    narrative = TickerNarrative(
        headline="JPMorgan valuation and profitability",
        summary=(
            "JPMorgan Chase & Co. last traded at 351.58 and is valued at USD 934.57 "
            "billion. It trades on a trailing P/E of 15.06x and a forward P/E of "
            "14.06x, with an operating margin of 50.39%, a profit margin of 34.92%, "
            "and a return on equity of 17.79%. Gross margin is not shown for this bank."
        ),
    )

    assert find_untraceable_numerals(narrative, _JPM_SNAPSHOT) == []
    check_numeric_fidelity(narrative, _JPM_SNAPSHOT)  # must not raise


# --- 10. The raise path: NumericFidelityError names the offending numeral ---


def test_check_numeric_fidelity_error_message_names_the_untraceable_numeral() -> None:
    fabricated = TickerNarrative(
        headline="BHP earnings multiple",
        summary="BHP Group Limited trades on a trailing P/E of 22.10x.",
    )
    with pytest.raises(NumericFidelityError) as exc_info:
        check_numeric_fidelity(fabricated, _BHP_SNAPSHOT)
    message = str(exc_info.value)
    assert "22.1" in message
    assert "summary" in message


# --- Thin regression check on the copied extract_numerals core ---


def test_extract_numerals_core_behaviour_is_preserved_from_macro_note() -> None:
    pct_bp_sign = {
        (m.value, m.unit) for m in extract_numerals("negative 43.0 basis points and up 4.28%")
    }
    assert (-43.0, "basis_points") in pct_bp_sign
    assert (4.28, "percent") in pct_bp_sign

    assert any(m.value == 12.0 for m in extract_numerals("twelve months of data"))
    assert extract_numerals("twenty-four months of data") == []
    assert any(m.value == -3.0 for m in extract_numerals("the differential was negative three"))

    assert any(m.value == 340878950400.0 for m in extract_numerals("a cap of 340,878,950,400"))

    iso = {(m.value, m.unit) for m in extract_numerals("as of 2026-08-24")}
    assert (2026.0, "unspecified") in iso
    assert (24.0, "unspecified") in iso
    assert (-8.0, "unspecified") not in iso
