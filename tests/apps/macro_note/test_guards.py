import json
from datetime import date
from pathlib import Path

import pytest

from apps.macro_note.guards import (
    NumericFidelityError,
    check_numeric_fidelity,
    extract_numerals,
    find_untraceable_numerals,
)
from apps.macro_note.models import FxCarry, Metric, MetricChange, NoteFacts, NoteNarrative, Section

FIXTURES_DIR = Path(__file__).parent / "fixtures"

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)


def _load_fixture_facts() -> NoteFacts:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_facts.json").read_text())
    return NoteFacts.model_validate(raw)


def _load_fixture_narrative() -> NoteNarrative:
    raw = json.loads((FIXTURES_DIR / "narrative_smoke_narrative.json").read_text())
    return NoteNarrative.model_validate(raw)


def _facts_with_bp_change(bp_change: float) -> NoteFacts:
    metric = Metric(
        series_id="us_10y",
        label="US 10-Year Treasury Yield",
        value=4.25,
        unit="%",
        as_of=date(2026, 7, 31),
        change_1d=_NO_CHANGE,
        change_1w=MetricChange(
            pct_change=None, bp_change=bp_change, reference_as_of=date(2026, 7, 24)
        ),
        change_1m=_NO_CHANGE,
    )
    return NoteFacts(
        note_date=date(2026, 7, 31), sections=[Section(title="Rates", metrics=[metric])]
    )


# --- The real fixture pair from #19 (required by issue scope) ---


def test_real_fixture_pair_is_fully_traceable() -> None:
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()

    assert find_untraceable_numerals(narrative, facts) == []
    check_numeric_fidelity(narrative, facts)  # must not raise


def test_fixture_narrative_traces_the_spelled_out_number() -> None:
    """The specific #19 finding: "two days ago" in the summary must trace."""
    facts = _load_fixture_facts()
    narrative = _load_fixture_narrative()
    assert "two days ago" in narrative.summary

    assert find_untraceable_numerals(narrative, facts) == []


# --- Deliberately fabricated figures (required by issue scope) ---


def test_deliberately_fabricated_figure_is_blocked() -> None:
    facts = _load_fixture_facts()
    fabricated = NoteNarrative(
        headline="Yields Surge",
        summary="US 10-Year yields jumped 17 basis points, an unusually sharp move.",
        bullets=["US 10-Year Treasury yield rose 17 basis points."],
    )

    untraceable = find_untraceable_numerals(fabricated, facts)

    assert len(untraceable) == 2  # one per mention: summary + bullet
    assert all(u.value == 17.0 and u.unit == "basis_points" for u in untraceable)
    with pytest.raises(NumericFidelityError):
        check_numeric_fidelity(fabricated, facts)


def test_fabricated_unrelated_number_with_no_coincidental_match_is_blocked() -> None:
    facts = _load_fixture_facts()
    narrative = NoteNarrative(
        headline="Update",
        summary="Yields have been rangebound for 15 consecutive sessions.",
        bullets=["No breakout in 15 sessions."],
    )

    untraceable = find_untraceable_numerals(narrative, facts)

    assert len(untraceable) == 2
    assert all(u.value == 15.0 and u.unit == "unspecified" for u in untraceable)


# --- Percent vs basis-point unit confusion ---


def test_percent_bp_unit_confusion_is_blocked() -> None:
    """2.0 is a real bp_change in the fixture, but claiming it as percent must fail."""
    facts = _load_fixture_facts()
    confused = NoteNarrative(
        headline="Yields Rise",
        summary="US 10-Year yields climbed 2% on the day.",
        bullets=["US 10-Year Treasury yield up 2% day-over-day."],
    )

    untraceable = find_untraceable_numerals(confused, facts)

    assert len(untraceable) == 2
    assert all(u.unit == "percent" and u.value == 2.0 for u in untraceable)


# --- Sign handling ---


def test_sign_stripped_magnitude_is_traceable() -> None:
    facts = _facts_with_bp_change(-5.0)
    narrative = NoteNarrative(
        headline="Yields Ease",
        summary="US 10-Year yields fell, down 5.0 basis points on the week.",
        bullets=["A 5.0 basis point weekly decline."],
    )

    assert find_untraceable_numerals(narrative, facts) == []


def test_flipped_sign_is_not_traceable() -> None:
    """One-directional: a positive payload value never accepts a narrated negative."""
    facts = _facts_with_bp_change(5.0)
    narrative = NoteNarrative(
        headline="Yields",
        summary="US 10-Year yields moved -5.0 basis points.",
        bullets=["Change of -5.0 basis points."],
    )

    untraceable = find_untraceable_numerals(narrative, facts)

    assert len(untraceable) == 2
    assert all(u.value == -5.0 for u in untraceable)


def test_word_number_matches_equivalent_digit_payload_value() -> None:
    facts = _facts_with_bp_change(2.0)
    narrative = NoteNarrative(
        headline="Yields",
        summary="Yields rose two basis points on the day.",
        bullets=["A two basis point increase."],
    )

    assert find_untraceable_numerals(narrative, facts) == []


# --- Date-component traceability ---


def test_day_of_month_from_date_field_is_traceable() -> None:
    facts = _load_fixture_facts()
    narrative = NoteNarrative(
        headline="Update",
        summary="As of July 31, conditions were stable.",
        bullets=["No material change since July 24."],
    )

    assert find_untraceable_numerals(narrative, facts) == []


# --- extract_numerals unit tests ---


def test_extract_numerals_handles_negative_word_and_percent_sign() -> None:
    matches = extract_numerals("negative 43.0 basis points and up 4.28%")
    values_by_unit = {(m.value, m.unit) for m in matches}

    assert (-43.0, "basis_points") in values_by_unit
    assert (4.28, "percent") in values_by_unit


def test_extract_numerals_parses_comma_thousands() -> None:
    matches = extract_numerals("The index closed at 8,432.10 points.")

    assert any(m.value == 8432.10 for m in matches)


def test_hyphenated_compound_word_number_is_not_decomposed() -> None:
    """ "twenty-five" must not silently extract as separate 20 and 5 matches."""
    assert extract_numerals("twenty-five days ago") == []


def test_extract_numerals_handles_negative_word_number() -> None:
    matches = extract_numerals("the differential was negative three percent")

    assert any(m.value == -3.0 and m.unit == "percent" for m in matches)


# --- FxCarry candidates ---


def test_fx_carry_fields_are_traceable() -> None:
    carry = FxCarry(
        label="AUD/USD Carry",
        annualised_return_pct=1.9,
        rate_differential_pct=-0.85,
        annualised_spot_change_pct=2.75,
        window_days=7,
    )
    facts = NoteFacts(
        note_date=date(2026, 7, 31),
        sections=[Section(title="FX", fx_carry=[carry])],
    )
    narrative = NoteNarrative(
        headline="Carry Update",
        summary=(
            "The AUD/USD carry trade returned 1.9% annualised, with a rate "
            "differential of negative 0.85% offset by a 2.75% annualised spot move "
            "over a 7-day window."
        ),
        bullets=["AUD/USD carry: 1.9% annualised over a 7-day window."],
    )

    assert find_untraceable_numerals(narrative, facts) == []


def test_fx_carry_window_days_is_unspecified_not_percent() -> None:
    """window_days is a day count, not a percentage -- claiming it as percent must fail."""
    carry = FxCarry(
        label="AUD/USD Carry",
        annualised_return_pct=1.9,
        rate_differential_pct=-0.85,
        annualised_spot_change_pct=2.75,
        window_days=7,
    )
    facts = NoteFacts(
        note_date=date(2026, 7, 31),
        sections=[Section(title="FX", fx_carry=[carry])],
    )
    narrative = NoteNarrative(
        headline="Carry Update",
        summary="The carry window was 7% of the observation period.",
        bullets=["7% window."],
    )

    untraceable = find_untraceable_numerals(narrative, facts)

    assert len(untraceable) == 2
    assert all(u.value == 7.0 and u.unit == "percent" for u in untraceable)
