"""Registry of the 12 series tracked by the Macro Research Digest MVP.

`source_code` is the identifier a connector uses to query the source:
- fred: the FRED series ID.
- rba: the RBA statistical table series ID (column header in the table's CSV).
- yfinance: the Yahoo Finance ticker.

RBA series IDs were confirmed by fetching the live CSVs on 2026-07-31:
- Cash Rate Target (daily) -> "FIRMMCRTD", Table F1 "Interest Rates and Yields
  - Money Market - Daily" (https://www.rba.gov.au/statistics/tables/csv/f1-data.csv).
  Not table F1.1, which carries the same series as a monthly average.
- AU 3-year and 10-year government bond yields (daily) -> "FCMYGBAG3D" and
  "FCMYGBAG10D", Table F2 "Capital Market Yields - Government Bonds - Daily"
  (https://www.rba.gov.au/statistics/tables/csv/f2-data.csv). Not table F2.1,
  which is the monthly variant of the same series.
Re-check these against the live CSVs if the RBA connector ever fails to find
a column, since the RBA renumbers and retires series IDs occasionally.
"""

from apps.macro_note.models import SeriesMeta

SERIES_REGISTRY: tuple[SeriesMeta, ...] = (
    SeriesMeta(
        series_id="us_2y",
        name="US 2-Year Treasury Yield",
        source="fred",
        source_code="DGS2",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="us_10y",
        name="US 10-Year Treasury Yield",
        source="fred",
        source_code="DGS10",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="us_fed_funds",
        name="US Effective Federal Funds Rate",
        source="fred",
        source_code="DFF",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="us_cpi_yoy",
        name="US CPI (Year-over-Year)",
        source="fred",
        source_code="CPIAUCSL",
        unit="index",
        category="inflation",
    ),
    SeriesMeta(
        series_id="aud_usd",
        name="AUD/USD",
        source="fred",
        source_code="DEXUSAL",
        unit="USD per AUD",
        category="fx",
    ),
    SeriesMeta(
        series_id="brent_crude",
        name="Brent Crude Oil",
        source="fred",
        source_code="DCOILBRENTEU",
        unit="USD/bbl",
        category="commodities",
    ),
    SeriesMeta(
        series_id="au_cash_rate",
        name="RBA Cash Rate Target",
        source="rba",
        source_code="FIRMMCRTD",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="au_3y",
        name="AU 3-Year Government Bond Yield",
        source="rba",
        source_code="FCMYGBAG3D",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="au_10y",
        name="AU 10-Year Government Bond Yield",
        source="rba",
        source_code="FCMYGBAG10D",
        unit="%",
        category="rates",
    ),
    SeriesMeta(
        series_id="gold",
        name="Gold",
        source="yfinance",
        source_code="GC=F",
        unit="USD/oz",
        category="commodities",
    ),
    SeriesMeta(
        series_id="copper",
        name="Copper",
        source="yfinance",
        source_code="HG=F",
        unit="USD/lb",
        category="commodities",
    ),
    SeriesMeta(
        series_id="asx200",
        name="ASX 200",
        source="yfinance",
        source_code="^AXJO",
        unit="index",
        category="equities",
    ),
)
