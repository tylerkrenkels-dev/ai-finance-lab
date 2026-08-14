from datetime import date

import pytest
from pydantic import ValidationError

from apps.comps.models import (
    ComparableTransactionRow,
    ComparableTransactionsTable,
    Deal,
    FilingSource,
)

# Real values from the DEFM14A investigation -- not invented placeholders.

_SPLUNK_SOURCE = FilingSource(
    company_name="Splunk, Inc.",
    cik="1353283",
    accession_number="0001140361-23-050211",
    document_url="https://www.sec.gov/Archives/edgar/data/1353283/000114036123050211/ny20011269x2_defm14a.htm",
    index_url="https://www.sec.gov/Archives/edgar/data/1353283/000114036123050211/0001140361-23-050211-index.htm",
    filed_date=date(2023, 10, 30),
    section_heading="Selected Transactions Analysis",
    approx_page_fraction=0.208,
    retrieved_at=date(2026, 8, 13),
    raw_excerpt_path="fixtures/raw/splunk-cisco-qatalyst.txt",
)

_CHART_SOURCE = FilingSource(
    company_name="Chart Industries, Inc.",
    cik="892553",
    accession_number="0001193125-25-198320",
    document_url="https://www.sec.gov/Archives/edgar/data/892553/000119312525198320/d52397ddefm14a.htm",
    index_url="https://www.sec.gov/Archives/edgar/data/892553/000119312525198320/0001193125-25-198320-index.htm",
    filed_date=date(2025, 9, 8),
    section_heading="Selected Transactions Analysis",
    approx_page_fraction=0.20,
    retrieved_at=date(2026, 8, 13),
    raw_excerpt_path="fixtures/raw/chart-bakerhughes-wellsfargo.txt",
)


def test_deal_completed_requires_completed_date() -> None:
    with pytest.raises(ValidationError):
        Deal(
            deal_id="splunk-cisco",
            target_name="Splunk, Inc.",
            acquiror_name="Cisco Systems, Inc.",
            announced_date=date(2023, 9, 21),
            status="completed",
            completed_date=None,
        )


def test_deal_pending_rejects_completed_date() -> None:
    with pytest.raises(ValidationError):
        Deal(
            deal_id="norfolk-southern-union-pacific",
            target_name="Norfolk Southern Corporation",
            acquiror_name="Union Pacific Corporation",
            announced_date=date(2025, 7, 28),
            status="pending",
            completed_date=date(2026, 1, 1),
        )


def test_deal_completed_construction() -> None:
    deal = Deal(
        deal_id="splunk-cisco",
        target_name="Splunk, Inc.",
        acquiror_name="Cisco Systems, Inc.",
        announced_date=date(2023, 9, 21),
        status="completed",
        completed_date=date(2024, 3, 18),
    )
    assert deal.status == "completed"


def test_deal_pending_construction() -> None:
    deal = Deal(
        deal_id="norfolk-southern-union-pacific",
        target_name="Norfolk Southern Corporation",
        acquiror_name="Union Pacific Corporation",
        announced_date=date(2025, 7, 28),
        status="pending",
    )
    assert deal.completed_date is None


def test_filing_source_rejects_malformed_accession_number() -> None:
    # model_copy(update=...) does not re-run validators, so a full model_validate
    # is required to actually exercise the accession_number field_validator.
    with pytest.raises(ValidationError):
        FilingSource.model_validate(
            _SPLUNK_SOURCE.model_dump() | {"accession_number": "not-an-accession-number"}
        )


def test_filing_source_rejects_non_digit_cik() -> None:
    with pytest.raises(ValidationError):
        FilingSource.model_validate(_SPLUNK_SOURCE.model_dump() | {"cik": "not-a-cik"})


def test_filing_source_rejects_non_sec_gov_url() -> None:
    with pytest.raises(ValidationError):
        FilingSource(
            company_name="Splunk, Inc.",
            cik="1353283",
            accession_number="0001140361-23-050211",
            document_url="https://example.com/fake-filing.htm",
            index_url=_SPLUNK_SOURCE.index_url,
            filed_date=date(2023, 10, 30),
            section_heading="Selected Transactions Analysis",
            approx_page_fraction=0.208,
            retrieved_at=date(2026, 8, 13),
            raw_excerpt_path="fixtures/raw/splunk-cisco-qatalyst.txt",
        )


def test_comparable_transaction_row_construction_with_multiples() -> None:
    row = ComparableTransactionRow(
        target="New Relic, Inc.",
        acquiror="Francisco Partners Management, L.P. & TPG Fund",
        announcement_period_raw="07/31/23",
        announcement_year=2023,
        multiples={
            "NTM Revenue Multiple": "5.8x",
            "NTM EBITDA Multiple": "30.4x",
            "NTM LFCF Multiple": "48.1x",
        },
    )
    assert row.multiples["NTM Revenue Multiple"] == "5.8x"
    assert row.footnote_refs == []


def test_comparable_transaction_row_allows_missing_multiple_as_none() -> None:
    row = ComparableTransactionRow(
        target="Software AG",
        acquiror="Silver Lake",
        announcement_period_raw="05/04/23",
        announcement_year=2023,
        multiples={"NTM Revenue Multiple": "2.6x", "NTM LFCF Multiple": None},
    )
    assert row.multiples["NTM LFCF Multiple"] is None


def test_table_with_three_multiple_columns_matches_splunk_shape() -> None:
    table = ComparableTransactionsTable(
        table_id="splunk-cisco-qatalyst",
        deal_id="splunk-cisco",
        advisor="Qatalyst Partners",
        analysis_label="Selected Transactions Analysis",
        source=_SPLUNK_SOURCE,
        multiple_columns=["NTM Revenue Multiple", "NTM EBITDA Multiple", "NTM LFCF Multiple"],
        rows=[
            ComparableTransactionRow(
                target="New Relic, Inc.",
                acquiror="Francisco Partners Management, L.P. & TPG Fund",
                announcement_period_raw="07/31/23",
                announcement_year=2023,
                multiples={
                    "NTM Revenue Multiple": "5.8x",
                    "NTM EBITDA Multiple": "30.4x",
                    "NTM LFCF Multiple": "48.1x",
                },
            ),
        ],
        expected_row_count=1,
    )
    assert table.multiple_columns == [
        "NTM Revenue Multiple",
        "NTM EBITDA Multiple",
        "NTM LFCF Multiple",
    ]


def test_table_with_zero_multiple_columns_matches_chart_shape() -> None:
    # Chart Industries' Wells Fargo table has no per-row multiple at all -- the
    # schema must represent this honestly, not force empty multiple fields.
    table = ComparableTransactionsTable(
        table_id="chart-bakerhughes-wellsfargo",
        deal_id="chart-bakerhughes",
        advisor="Wells Fargo Securities",
        analysis_label="Selected Transactions Analysis",
        source=_CHART_SOURCE,
        multiple_columns=[],
        rows=[
            ComparableTransactionRow(
                target="Howden",
                acquiror="Chart Industries, Inc.",
                announcement_period_raw="November 2022",
                announcement_year=2022,
            ),
        ],
        expected_row_count=1,
    )
    assert table.multiple_columns == []
    assert table.rows[0].multiples == {}


def test_table_with_summary_stats_and_no_row_multiples_matches_foot_locker_shape() -> None:
    # Foot Locker's Evercore table lists transactions with no per-row multiple,
    # and reports Mean/Median/Low/High separately -- summary_stats exists for this.
    table = ComparableTransactionsTable(
        table_id="footlocker-dicks-evercore",
        deal_id="footlocker-dicks",
        advisor="Evercore",
        analysis_label="Selected Transactions Analysis",
        source=_CHART_SOURCE.model_copy(update={"company_name": "Foot Locker, Inc."}),
        multiple_columns=[],
        rows=[
            ComparableTransactionRow(
                target="Hibbett, Inc.",
                acquiror="JD Sports Fashion PLC",
                announcement_period_raw="April 2024",
                announcement_year=2024,
            ),
        ],
        expected_row_count=1,
        summary_stats={
            "TEV / LTM Adjusted EBITDA": {
                "Mean": "7.4x",
                "Median": "6.9x",
                "Low": "3.7x",
                "High": "10.9x",
            },
        },
    )
    assert table.summary_stats is not None
    assert table.summary_stats["TEV / LTM Adjusted EBITDA"]["Mean"] == "7.4x"


def test_table_rejects_row_count_mismatch() -> None:
    with pytest.raises(ValidationError):
        ComparableTransactionsTable(
            table_id="chart-bakerhughes-wellsfargo",
            deal_id="chart-bakerhughes",
            advisor="Wells Fargo Securities",
            analysis_label="Selected Transactions Analysis",
            source=_CHART_SOURCE,
            multiple_columns=[],
            rows=[
                ComparableTransactionRow(
                    target="Howden",
                    acquiror="Chart Industries, Inc.",
                    announcement_period_raw="November 2022",
                    announcement_year=2022,
                ),
            ],
            expected_row_count=10,  # the real Chart table has 10 rows; only 1 is given here
        )


def test_table_rejects_row_multiple_not_in_declared_columns() -> None:
    with pytest.raises(ValidationError):
        ComparableTransactionsTable(
            table_id="splunk-cisco-qatalyst",
            deal_id="splunk-cisco",
            advisor="Qatalyst Partners",
            analysis_label="Selected Transactions Analysis",
            source=_SPLUNK_SOURCE,
            multiple_columns=["NTM Revenue Multiple"],
            rows=[
                ComparableTransactionRow(
                    target="New Relic, Inc.",
                    acquiror="Francisco Partners Management, L.P. & TPG Fund",
                    announcement_period_raw="07/31/23",
                    announcement_year=2023,
                    # NTM EBITDA Multiple is not declared in multiple_columns above.
                    multiples={"NTM Revenue Multiple": "5.8x", "NTM EBITDA Multiple": "30.4x"},
                ),
            ],
            expected_row_count=1,
        )


def test_two_tables_can_share_one_deal_id() -> None:
    # Norfolk Southern/Union Pacific: Wells Fargo and BofA each produced their own
    # table from the same filing, for the same deal.
    wells_fargo_row = ComparableTransactionRow(
        target="Kansas City Southern",
        acquiror="Canadian Pacific Railway Limited",
        announcement_period_raw="2021",
        announcement_year=2021,
        multiples={"TEV/LTM EBITDA Multiple": "19.5x"},
        footnote_refs=["[a]"],
    )
    bofa_row = ComparableTransactionRow(
        target="Kansas City Southern",
        acquiror="Canadian Pacific Railway Limited",
        announcement_period_raw="09/21",
        announcement_year=2021,
        multiples={"TEV/LTM Adj. EBITDA": "21.2x"},
    )
    norfolk_source = _SPLUNK_SOURCE.model_copy(
        update={
            "company_name": "Norfolk Southern Corporation",
            "section_heading": "Selected Transactions Analysis",
        }
    )
    wells_fargo_table = ComparableTransactionsTable(
        table_id="norfolk-southern-union-pacific-wells-fargo",
        deal_id="norfolk-southern-union-pacific",
        advisor="Wells Fargo Securities, LLC",
        analysis_label="Selected Transactions Analysis",
        source=norfolk_source,
        multiple_columns=["TEV/LTM EBITDA Multiple"],
        rows=[wells_fargo_row],
        expected_row_count=1,
        footnotes={"[a]": "EBITDA adjusted for the estimated impact of COVID-19."},
    )
    bofa_table = ComparableTransactionsTable(
        table_id="norfolk-southern-union-pacific-bofa",
        deal_id="norfolk-southern-union-pacific",
        advisor="BofA Securities, Inc.",
        analysis_label="Selected Precedent Transactions Analysis",
        source=norfolk_source,
        multiple_columns=["TEV/LTM Adj. EBITDA"],
        rows=[bofa_row],
        expected_row_count=1,
    )
    assert wells_fargo_table.deal_id == bofa_table.deal_id == "norfolk-southern-union-pacific"
    assert wells_fargo_table.analysis_label != bofa_table.analysis_label
