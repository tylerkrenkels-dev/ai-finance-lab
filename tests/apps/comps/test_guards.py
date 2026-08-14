from pathlib import Path

import pytest

from apps.comps.guards import (
    StructuralFidelityError,
    check_structural_fidelity,
    find_untraceable_cells,
    load_raw_excerpt,
)
from apps.comps.registry import TABLES

_WELLS_FARGO_TABLE = next(
    t for t in TABLES if t.table_id == "norfolk-southern-union-pacific-wells-fargo"
)
_WELLS_FARGO_EXCERPT = (
    Path(__file__).parents[3] / "apps/comps" / _WELLS_FARGO_TABLE.source.raw_excerpt_path
).read_text(encoding="utf-8")


def test_clean_wells_fargo_table_passes_against_its_real_fixture() -> None:
    assert find_untraceable_cells(_WELLS_FARGO_TABLE, _WELLS_FARGO_EXCERPT) == []
    check_structural_fidelity(_WELLS_FARGO_TABLE, _WELLS_FARGO_EXCERPT)  # must not raise


def test_digit_swap_on_multiple_is_caught() -> None:
    # Real row: Kansas City Southern / Canadian Pacific Railway Limited / 19.5x / [a].
    # Corrupt 19.5x -> 19.6x -- a value that does not appear anywhere in the fixture.
    corrupted_row = _WELLS_FARGO_TABLE.rows[0].model_copy(
        update={"multiples": {"TEV /LTM EBITDA Multiple": "19.6x"}}
    )
    corrupted_table = _WELLS_FARGO_TABLE.model_copy(
        update={"rows": [corrupted_row, *_WELLS_FARGO_TABLE.rows[1:]]}
    )

    untraceable = find_untraceable_cells(corrupted_table, _WELLS_FARGO_EXCERPT)
    assert len(untraceable) == 1
    assert untraceable[0].value == "19.6x"

    with pytest.raises(StructuralFidelityError):
        check_structural_fidelity(corrupted_table, _WELLS_FARGO_EXCERPT)


def test_every_real_registry_table_passes_against_its_own_fixture() -> None:
    # Not just Wells Fargo: all 6 real, unmodified tables against their own real
    # fixtures -- the guard's actual end-to-end job, per registry.py's own docstring.
    for table in TABLES:
        excerpt = load_raw_excerpt(table)
        untraceable = find_untraceable_cells(table, excerpt)
        assert untraceable == [], f"{table.table_id}: {untraceable}"
        check_structural_fidelity(table, excerpt)


def test_fabricated_footnote_text_is_caught() -> None:
    # Real footnote: "[a]" -> "EBITDA adjusted for the estimated impact of COVID-19."
    # Corrupt it to a sentence that appears nowhere in the fixture. This must be
    # caught even though target/acquiror/multiples on every row are untouched --
    # footnotes is a genuinely different field on the table, not row-level data.
    fabricated_text = "This sentence was fabricated and does not appear in the source filing."
    corrupted_table = _WELLS_FARGO_TABLE.model_copy(
        update={"footnotes": {**_WELLS_FARGO_TABLE.footnotes, "[a]": fabricated_text}}
    )

    untraceable = find_untraceable_cells(corrupted_table, _WELLS_FARGO_EXCERPT)
    assert len(untraceable) == 1
    assert untraceable[0].value == fabricated_text

    with pytest.raises(StructuralFidelityError):
        check_structural_fidelity(corrupted_table, _WELLS_FARGO_EXCERPT)
