from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic

from apps.macro_note.models import Metric, MetricChange, NoteFacts, NoteNarrative, Section
from apps.macro_note.narrative import AnthropicSettings, NarrativeGenerator

NOTE_DATE = date(2026, 7, 31)

_NO_CHANGE = MetricChange(pct_change=None, bp_change=None, reference_as_of=None)


def _settings() -> AnthropicSettings:
    return AnthropicSettings(anthropic_api_key="test-key")


def _facts() -> NoteFacts:
    metric = Metric(
        series_id="us_10y",
        label="US 10-Year Treasury Yield",
        value=4.25,
        unit="%",
        as_of=NOTE_DATE,
        change_1d=_NO_CHANGE,
        change_1w=_NO_CHANGE,
        change_1m=_NO_CHANGE,
    )
    return NoteFacts(
        note_date=NOTE_DATE,
        sections=[Section(title="Rates", metrics=[metric])],
    )


def _narrative() -> NoteNarrative:
    return NoteNarrative(
        headline="Yields hold steady",
        summary="The US 10-Year Treasury Yield stood at 4.25% as of 2026-07-31.",
        bullets=["US 10-Year Treasury Yield: 4.25%"],
    )


def test_generate_returns_parsed_narrative() -> None:
    expected = _narrative()
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=expected)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    narrative = generator.generate(_facts())

    assert narrative == expected
    mock_client.messages.parse.assert_called_once()


def test_generate_makes_exactly_one_api_call() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    assert mock_client.messages.parse.call_count == 1


def test_generate_calls_with_expected_model_and_temperature() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    _, kwargs = mock_client.messages.parse.call_args
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["temperature"] == 0
    assert kwargs["output_format"] is NoteNarrative


def test_generate_system_prompt_forbids_computation() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    generator.generate(_facts())

    _, kwargs = mock_client.messages.parse.call_args
    system = kwargs["system"]
    assert "never calculate, estimate, infer" in system
    assert "reproduced exactly as given" in system


def test_generate_prompt_includes_facts_as_json() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=_narrative())
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)
    facts = _facts()

    generator.generate(facts)

    _, kwargs = mock_client.messages.parse.call_args
    user_content = kwargs["messages"][0]["content"]
    assert facts.model_dump_json(indent=2) in user_content


def test_generate_raises_when_parsed_output_is_none() -> None:
    mock_client = MagicMock()
    mock_client.messages.parse.return_value = SimpleNamespace(parsed_output=None)
    generator = NarrativeGenerator(settings=_settings(), client=mock_client)

    try:
        generator.generate(_facts())
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when parsed_output is None")


def test_narrative_generator_constructs_client_from_settings_when_omitted() -> None:
    # Constructing anthropic.Anthropic() only stores the key; it makes no network call.
    generator = NarrativeGenerator(settings=_settings())

    assert isinstance(generator._client, anthropic.Anthropic)
