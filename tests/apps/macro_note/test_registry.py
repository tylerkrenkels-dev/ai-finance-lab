from apps.macro_note.models import SeriesMeta
from apps.macro_note.registry import SERIES_REGISTRY


def test_registry_has_twelve_series() -> None:
    assert len(SERIES_REGISTRY) == 12


def test_registry_entries_are_series_meta() -> None:
    assert all(isinstance(entry, SeriesMeta) for entry in SERIES_REGISTRY)


def test_registry_series_ids_are_unique() -> None:
    series_ids = [entry.series_id for entry in SERIES_REGISTRY]
    assert len(series_ids) == len(set(series_ids))


def test_registry_source_codes_are_unique_per_source() -> None:
    keys = [(entry.source, entry.source_code) for entry in SERIES_REGISTRY]
    assert len(keys) == len(set(keys))


def test_registry_source_counts_match_mvp_sources() -> None:
    sources = [entry.source for entry in SERIES_REGISTRY]
    assert sources.count("fred") == 6
    assert sources.count("rba") == 3
    assert sources.count("yfinance") == 3


def test_registry_contains_expected_series_ids() -> None:
    expected = {
        "us_2y",
        "us_10y",
        "us_fed_funds",
        "us_cpi_yoy",
        "aud_usd",
        "brent_crude",
        "au_cash_rate",
        "au_3y",
        "au_10y",
        "gold",
        "copper",
        "asx200",
    }
    actual = {entry.series_id for entry in SERIES_REGISTRY}
    assert actual == expected


def test_registry_rba_series_use_daily_codes() -> None:
    rba_codes = {entry.source_code for entry in SERIES_REGISTRY if entry.source == "rba"}
    assert rba_codes == {"FIRMMCRTD", "FCMYGBAG3D", "FCMYGBAG10D"}
