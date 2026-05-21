import pandas as pd
import pytest

from fidelity_csv_to_markdown import ConvertResult, convert_csv


def test_happy_path_dry_run(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, contract, tmp_path, dry_run=True)

    assert isinstance(result, ConvertResult)
    assert result.account_name == "Individual - TOD"
    assert result.account_number == "X10000001"
    assert result.positions == 5
    assert result.dry_run is True
    assert result.size == "dry-run"
    assert not result.out_path.exists()


def test_happy_path_writes_file(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, contract, tmp_path, dry_run=False)

    assert result.out_path.exists()
    assert result.out_path.name == "individual_-_tod__x10000001.md"
    body = result.out_path.read_text(encoding="utf-8")
    assert "X10000001" in body
    assert "VTI" in body
    assert "AAPL" in body
    # Header lines precede the table; the table itself still starts with "|".
    lines = body.splitlines()
    assert any(line.startswith("|") for line in lines)


def test_summary_header_emitted(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, contract, tmp_path, dry_run=False)
    body = result.out_path.read_text(encoding="utf-8")

    # As-of timestamp extracted from the dropped "Date downloaded ..." footer.
    assert "**As of:** Apr-03-2026 12:01 p.m ET" in body
    # Sum of Current value across the fixture's 6 rows = $100,000.00
    assert "**Total Current Value:** $100,000.00" in body
    # Header appears above the table
    header_idx = body.index("**As of:**")
    table_idx = body.index("|")
    assert header_idx < table_idx


def test_convert_result_exposes_as_of_and_totals(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, contract, tmp_path, dry_run=True)
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.totals == [("Total Current Value", "$100,000.00")]


def test_summary_header_disabled(fixture_csv_path, contract, tmp_path):
    disabled = {
        **contract,
        "output": {
            **contract.get("output", {}),
            "markdown": {
                **contract.get("output", {}).get("markdown", {}),
                "summary_header": {"enabled": False},
            },
        },
    }
    result = convert_csv(fixture_csv_path, disabled, tmp_path, dry_run=False)
    body = result.out_path.read_text(encoding="utf-8")

    assert "**As of:**" not in body
    assert "**Total Current Value:**" not in body
    assert body.startswith("|")
    assert result.as_of is None
    assert result.totals == []


def test_summary_header_missing_totals_column_skipped(fixture_csv_path, contract, tmp_path):
    bogus = {
        **contract,
        "output": {
            **contract.get("output", {}),
            "markdown": {
                **contract.get("output", {}).get("markdown", {}),
                "summary_header": {
                    "enabled": True,
                    "as_of": {"pattern": r"Date downloaded\s+(.+)"},
                    "totals": [{"label": "Bogus", "column": "NotARealColumn"}],
                },
            },
        },
    }
    result = convert_csv(fixture_csv_path, bogus, tmp_path, dry_run=True)
    # As-of still extracted; bogus total skipped, no totals line emitted.
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.totals == []


def test_vti_appears_twice_in_position_pairs(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, contract, tmp_path, dry_run=True)
    vti_count = next(
        count for (sym, _), count in result.position_pairs.items() if sym == "VTI"
    )
    assert vti_count == 2


def test_multi_account_rejected(fixture_df, contract, write_csv, tmp_path):
    clone = fixture_df.iloc[[0]].copy()
    clone["Account Number"] = "X20000002"
    clone["Account Name"] = "Other Account"
    multi = pd.concat([fixture_df, clone], ignore_index=True)
    csv = write_csv(multi, "multi.csv")

    with pytest.raises(AssertionError, match="multi-account CSV detected"):
        convert_csv(csv, contract, tmp_path, dry_run=True)


def test_collision_rejected(fixture_csv_path, contract, tmp_path):
    convert_csv(fixture_csv_path, contract, tmp_path, dry_run=False)

    with pytest.raises(AssertionError, match="output collision"):
        convert_csv(fixture_csv_path, contract, tmp_path, dry_run=False)


def test_missing_required_column_rejected(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.drop(columns=["Account Name"])
    csv = write_csv(df, "no_account_name.csv")

    with pytest.raises(AssertionError, match="required column missing: 'Account Name'"):
        convert_csv(csv, contract, tmp_path, dry_run=True)


def test_missing_symbol_column_rejected(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.drop(columns=["Symbol"])
    csv = write_csv(df, "no_symbol.csv")

    with pytest.raises(AssertionError, match="required column missing: 'Symbol'"):
        convert_csv(csv, contract, tmp_path, dry_run=True)


def test_empty_after_cleanup(fixture_df, contract, write_csv, tmp_path):
    # Replace every data row's Account Number with the drop_rows pattern.
    df = fixture_df.copy()
    df["Account Number"] = "Date downloaded"
    csv = write_csv(df, "all_dropped.csv")

    with pytest.raises(AssertionError, match="no rows after cleanup"):
        convert_csv(csv, contract, tmp_path, dry_run=True)


def test_positions_lost_during_cleanup(fixture_df, contract, write_csv, tmp_path):
    # Force a legitimate position row to match the drop_rows regex.
    df = fixture_df.copy()
    df.loc[0, "Account Number"] = "Date downloaded"
    csv = write_csv(df, "position_lost.csv")

    with pytest.raises(AssertionError, match="positions lost during cleanup"):
        convert_csv(csv, contract, tmp_path, dry_run=True)


def test_column_aliases_applied(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.rename(columns={"Symbol": "Ticker"})
    csv = write_csv(df, "aliased.csv")

    aliased_contract = {
        **contract,
        "input_cleanup": {
            **contract["input_cleanup"],
            "column_aliases": {"Ticker": "Symbol"},
        },
    }

    result = convert_csv(csv, aliased_contract, tmp_path, dry_run=True)
    assert result.positions == 5


def test_drop_columns_removes_columns(fixture_csv_path, contract, tmp_path):
    dropped_contract = {
        **contract,
        "input_cleanup": {
            **contract["input_cleanup"],
            "drop_columns": ["Sector", "Industry"],
        },
    }

    result = convert_csv(fixture_csv_path, dropped_contract, tmp_path, dry_run=False)
    body = result.out_path.read_text(encoding="utf-8")
    header_line = next(line for line in body.splitlines() if line.startswith("|"))
    headers = [h.strip() for h in header_line.strip("|").split("|")]
    assert "Sector" not in headers
    assert "Industry" not in headers
    # Sibling columns like "Industry group" should still be present
    assert "Industry group" in headers
