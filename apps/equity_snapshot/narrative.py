"""Turns an EquitySnapshot payload into prose via exactly one Anthropic API call.

The model receives already-computed, validated figures for one ticker and
writes prose about them. It never computes, estimates, infers, or restates a
figure that is not already in EquitySnapshot -- that invariant is instructed
here and will be mechanically enforced downstream by a numeric fidelity guard
(a later issue), mirroring apps.macro_note.narrative's own design exactly:

- Plain messages.create(), never messages.parse()/output_format. Confirmed by
  reading anthropic's own lib/_parse/_response.py during macro_note's #19/#44:
  when structured-output validation fails, the SDK discards the model's raw
  text before a pydantic.ValidationError reaches calling code, with no
  accessible recovery hook, and array max-length constraints aren't even
  forwarded to the API as hard constraints anyway. This module asks for the
  JSON shape entirely via prompt instructions and validates the returned text
  itself, so a validation failure can still log exactly what the model wrote.
- SYSTEM_PROMPT's digit-form instruction is a best-effort nudge, not a
  guarantee -- macro_note's #19 showed claude-haiku-4-5 at temperature=0
  following it in some output fields but not others for the same fact in the
  same response. The eventual guard here must independently verify every
  numeral against EquitySnapshot and accept both digit and spelled-out
  small-number forms, not assume this prompt's instruction was followed.

One risk specific to THIS system, absent from macro_note: EquitySnapshot's
data_warnings don't just report that a figure is missing (macro_note's are
almost entirely about staleness) -- some explain the mechanism, e.g. "EV/EBITDA
not shown: BHP Group Limited's trading currency (AUD) differs from its
reporting currency (USD)." That sentence hands the model both currency codes,
inviting it to "helpfully" compute an FX-adjusted estimate -- exactly the kind
of number the core invariant forbids, and a temptation macro_note's
staleness-only warnings never created. SYSTEM_PROMPT has a paragraph
specifically targeting this, not just macro_note's generic data_warnings
paragraph reused verbatim.

TickerNarrative has no bullets, unlike NoteNarrative: a macro note covers
genuinely separate topics (rates, FX, commodities) that read better itemized;
one ticker's ~7 valuation/profitability figures form one coherent story, not
enough independent threads to justify a list.

_extract_text/_strip_code_fence are near-duplicates of
apps.macro_note.narrative's versions. This is intentional, not an oversight:
per CLAUDE.md's rule of three, this is only the second app needing this
scaffolding, not yet three, so core/ stays empty and the duplication is
correct and accepted until a third real use demonstrates the shared need.
"""

import anthropic
import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.equity_snapshot.payload import EquitySnapshot

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 512  # provisional: headline + one paragraph needs far less than
# macro_note's 1024 (headline + summary + up to 9 bullets), but unlike
# macro_note's bullets cap (max_length=9, set from actual live dry runs in
# #44), this has not yet been validated against real output length -- treat
# as a starting bound pending a live dry run, not an evidenced constraint.

_PARAGRAPHS = [
    (
        "You are a financial writer producing a brief narrative for a single-company "
        "equity snapshot. You will be given a JSON payload of already-computed valuation "
        "and profitability metrics for one ticker: price, market capitalization, trailing "
        "and forward P/E, EV/EBITDA, gross/operating/profit margin, and return on equity. "
        "Every number in that payload has already been calculated and validated by other "
        "software before it reached you."
    ),
    (
        "Your job is to write a short narrative describing this ticker's current "
        "valuation and profitability profile: a headline and a one-paragraph summary. "
        "You may reference any number that already appears in the payload, exactly as it "
        "appears there."
    ),
    (
        "Respond with a single JSON object and nothing else: no markdown code fences, no "
        "text before or after the JSON. The object must have exactly two fields: "
        '"headline" (a string) and "summary" (a string). Do not include any other fields.'
    ),
    (
        "You must never calculate, estimate, infer, interpolate, round differently, "
        "average, or otherwise produce a number that is not already present in the "
        "payload. This includes simple-seeming arithmetic, such as a difference between "
        "two figures or a ratio between two values. If a comparison would require "
        "arithmetic you have not been given the result of, describe the relationship in "
        'words only (for example "richer," "cheaper," "wider," "narrower") without '
        "stating a new number."
    ),
    (
        "Numbers you do use from the payload must be reproduced exactly as given, not "
        "re-rounded or reformatted for readability. For example, a trailing_pe of 24.76 "
        'must appear as "24.76x" or "24.76", never as "24.8x" or "about 25x". Do not '
        "adjust precision, add or drop trailing digits, or paraphrase a figure into an "
        "approximation, even if the exact figure looks awkward in a sentence. Numbers "
        "must always be written in digit form exactly as they appear in the payload, "
        'never spelled out as words (for example "24.76," never "twenty-four point '
        'seven six").'
    ),
    (
        "If the payload's data_warnings list is non-empty, you may mention that a figure "
        "is not shown, using only the information given in that list -- but some of these "
        "warnings explain why a figure could not be computed (for example, that the "
        "ticker's trading currency differs from its financial reporting currency, or that "
        "a metric is not economically meaningful for its sector). That explanation is "
        "context for the reader, not an invitation to compute, convert, or estimate the "
        "missing figure yourself -- not even as an approximate or illustrative number, "
        "and not even if the conversion seems straightforward from the information given. "
        "If a figure is not in the payload, it does not appear in your narrative at all, "
        'under any label such as "approximately" or "roughly".'
    ),
    (
        "Write in a neutral, professional register suitable for institutional readers. "
        "Do not use markdown formatting in your output fields."
    ),
]

SYSTEM_PROMPT = "\n\n".join(_PARAGRAPHS)


class AnthropicSettings(BaseSettings):
    """Anthropic API credentials, read from .env. Never hardcoded."""

    anthropic_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class TickerNarrative(pydantic.BaseModel):
    """The only output an LLM call returns for one ticker: prose fields, no numeric fields."""

    headline: str
    summary: str


class NarrativeParseError(RuntimeError):
    """Raised when the model's response text did not validate into TickerNarrative.

    Carries the raw response text -- the one piece of information a bare
    pydantic.ValidationError discards -- so a parse failure can still be
    diagnosed from the logs instead of leaving only a shape mismatch.
    """

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


class NarrativeGenerator:
    """Generates a TickerNarrative from an EquitySnapshot via the Anthropic API."""

    def __init__(
        self,
        settings: AnthropicSettings | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        # mypy sees anthropic_api_key as a required constructor arg; pydantic-settings
        # actually supplies it from the environment/.env at runtime.
        self._settings = settings or AnthropicSettings()  # type: ignore[call-arg]
        self._client = client or anthropic.Anthropic(api_key=self._settings.anthropic_api_key)

    def generate(self, snapshot: EquitySnapshot) -> TickerNarrative:
        """Call the Anthropic API once, turning `snapshot` into a TickerNarrative."""
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(snapshot)}],
        )
        text = _extract_text(response)

        candidates = [text]
        unfenced = _strip_code_fence(text)
        if unfenced is not None:
            candidates.append(unfenced)

        last_error: pydantic.ValidationError | None = None
        for candidate in candidates:
            try:
                return TickerNarrative.model_validate_json(candidate)
            except pydantic.ValidationError as exc:
                last_error = exc

        raise NarrativeParseError(
            f"Model response did not validate into TickerNarrative: {last_error}",
            raw_text=text,
        ) from last_error


def _extract_text(response: anthropic.types.Message) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    raise NarrativeParseError(
        "Anthropic response contained no text block", raw_text=str(response.content)
    )


def _strip_code_fence(text: str) -> str | None:
    """Strips a single wrapping ``` or ```json code fence, or returns None if
    `text` isn't fenced.

    The prompt explicitly asks for no fences, but wrapping JSON in a markdown
    code block is a common enough model habit that it's worth recovering from
    before failing the run over otherwise-valid content -- unlike a genuine
    content violation, a fence is a cosmetic artifact around the JSON, not a
    data-integrity problem. This is tried only as a fallback after the raw
    text fails to parse; see generate().
    """
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return None


def _build_prompt(snapshot: EquitySnapshot) -> str:
    return (
        f"The computed equity snapshot for {snapshot.ticker}, as JSON. Write the "
        f"narrative based only on these figures.\n\n{snapshot.model_dump_json(indent=2)}"
    )
