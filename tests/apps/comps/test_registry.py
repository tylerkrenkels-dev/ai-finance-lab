from apps.comps.registry import DEALS, TABLES


def test_registry_has_five_deals_and_six_tables() -> None:
    assert len(DEALS) == 5
    assert len(TABLES) == 6


def test_every_table_deal_id_resolves_to_a_real_deal() -> None:
    deal_ids = {d.deal_id for d in DEALS}
    for table in TABLES:
        assert table.deal_id in deal_ids, f"{table.table_id} references unknown deal_id"


def test_no_duplicate_table_ids() -> None:
    table_ids = [t.table_id for t in TABLES]
    assert len(table_ids) == len(set(table_ids))


def test_no_duplicate_deal_ids() -> None:
    deal_ids = [d.deal_id for d in DEALS]
    assert len(deal_ids) == len(set(deal_ids))


def test_row_counts_match_investigation() -> None:
    # These counts were independently re-verified against a fresh live re-fetch of
    # each filing before transcription (see registry.py's module docstring).
    expected = {
        "splunk-cisco-qatalyst": 68,
        "ansys-synopsys-qatalyst": 27,
        "norfolk-southern-union-pacific-wells-fargo": 12,
        "norfolk-southern-union-pacific-bofa": 20,
        "footlocker-dicks-evercore": 13,
        "chart-bakerhughes-wellsfargo": 10,
    }
    actual = {t.table_id: len(t.rows) for t in TABLES}
    assert actual == expected


def test_norfolk_southern_has_two_tables_from_two_advisors() -> None:
    norfolk_tables = [t for t in TABLES if t.deal_id == "norfolk-southern-union-pacific"]
    assert len(norfolk_tables) == 2
    advisors = {t.advisor for t in norfolk_tables}
    assert advisors == {"Wells Fargo Securities, LLC", "BofA Securities, Inc."}
    labels = {t.analysis_label for t in norfolk_tables}
    assert labels == {"Selected Transactions Analysis", "Selected Precedent Transactions Analysis"}


def test_splunk_first_row_matches_investigated_excerpt() -> None:
    table = next(t for t in TABLES if t.table_id == "splunk-cisco-qatalyst")
    first = table.rows[0]
    assert first.target == "New Relic, Inc."
    assert first.acquiror == "Francisco Partners Management, L.P. & TPG Fund"
    assert first.multiples == {
        "NTM Revenue Multiple": "5.8x",
        "NTM EBITDA Multiple": "30.4x",
        "NTM LFCF Multiple": "48.1x",
    }


def test_ansys_last_row_has_none_multiple_for_bare_hyphen() -> None:
    table = next(t for t in TABLES if t.table_id == "ansys-synopsys-qatalyst")
    last = table.rows[-1]
    assert last.target == "Medidata Solutions, Inc."
    assert last.multiples["NTM LFCF MULTIPLE"] is None


def test_foot_locker_rows_have_no_multiples_but_do_have_summary_stats() -> None:
    table = next(t for t in TABLES if t.table_id == "footlocker-dicks-evercore")
    assert all(row.multiples == {} for row in table.rows)
    assert table.summary_stats == {
        "TEV / LTM Adjusted EBITDA": {
            "Mean": "7.4x",
            "Median": "6.9x",
            "Low": "3.7x",
            "High": "10.9x",
        },
    }


def test_foot_locker_columns_were_remapped_not_copied_positionally() -> None:
    # Source prints "Acquirer | Target" (reversed vs. every other filing); the first
    # source row is "August 2024 | Frasers Group PLC | Accent Group Limited (minority
    # stake)" -- Frasers Group PLC is the acquiror, not the target.
    table = next(t for t in TABLES if t.table_id == "footlocker-dicks-evercore")
    first = table.rows[0]
    assert first.acquiror == "Frasers Group PLC"
    assert first.target == "Accent Group Limited (minority stake)"


def test_chart_rows_have_no_multiple_columns_at_all() -> None:
    table = next(t for t in TABLES if t.table_id == "chart-bakerhughes-wellsfargo")
    assert table.multiple_columns == []
    assert all(row.multiples == {} for row in table.rows)


def test_wells_fargo_norfolk_table_carries_footnotes_and_summary_stats() -> None:
    table = next(t for t in TABLES if t.table_id == "norfolk-southern-union-pacific-wells-fargo")
    assert table.footnotes["[a]"] == "EBITDA adjusted for the estimated impact of COVID-19."
    assert table.summary_stats == {"TEV /LTM EBITDA Multiple": {"Mean": "11.6x", "Median": "11.8x"}}
    kansas_city_row = table.rows[0]
    assert kansas_city_row.target == "Kansas City Southern"
    assert kansas_city_row.footnote_refs == ["[a]"]


def test_bofa_norfolk_footnote_marker_is_embedded_in_acquiror_string() -> None:
    # BofA's footnote convention differs from Wells Fargo's: "(1)" is embedded
    # inline in the acquiror's printed name, not a separate trailing cell.
    table = next(t for t in TABLES if t.table_id == "norfolk-southern-union-pacific-bofa")
    row = next(r for r in table.rows if "(1)" in r.acquiror)
    assert row.acquiror == "Rail Consortium (1)"
    assert row.footnote_refs == ["(1)"]
    assert "(1)" in table.footnotes


def test_pending_deal_has_no_completed_date() -> None:
    norfolk = next(d for d in DEALS if d.deal_id == "norfolk-southern-union-pacific")
    assert norfolk.status == "pending"
    assert norfolk.completed_date is None


def test_completed_deals_all_have_completed_dates() -> None:
    for deal in DEALS:
        if deal.status == "completed":
            assert deal.completed_date is not None
