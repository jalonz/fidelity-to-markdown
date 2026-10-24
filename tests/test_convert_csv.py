import csv
import re
from dataclasses import replace

import pytest

from fidelity_csv_to_markdown import CONTRACT, AccountSection, ConvertResult, Total, convert_csv


def test_happy_path_dry_run(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True, contract=contract)

    assert isinstance(result, ConvertResult)
    assert len(result.accounts) == 1
    section = result.accounts[0]
    assert isinstance(section, AccountSection)
    assert section.account_name == "Individual - TOD"
    assert section.account_number == "X10000001"
    # 6 holdings: the two identical VTI lots count separately.
    assert section.positions == 6
    assert result.dry_run is True
    assert result.size == "dry-run"
    assert not result.out_path.exists()


def test_happy_path_writes_file(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=contract)

    assert result.out_path.exists()
    # Filename now derives from the input CSV stem (not account_name__number).
    assert result.out_path.name == "fidelity_positions_test.md"
    body = result.out_path.read_text(encoding="utf-8")
    assert "X10000001" in body
    assert "VTI" in body
    assert "AAPL" in body
    # One account → one section under an H2 heading.
    assert "## Individual - TOD (X10000001)" in body
    lines = body.splitlines()
    assert any(line.startswith("|") for line in lines)


def test_summary_header_emitted(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=contract)
    body = result.out_path.read_text(encoding="utf-8")

    # As-of timestamp extracted from the dropped "Date downloaded ..." footer.
    assert "**As of:** Apr-03-2026 12:01 p.m ET" in body
    # Sum of Current value across the fixture's 6 rows = $100,000.00
    assert "**Total Current Value:** $100,000.00" in body
    # Account index (single account → its subtotal == the portfolio total).
    assert "- Individual - TOD (X10000001): $100,000.00" in body
    # Portfolio header appears above the first section heading.
    assert body.index("**As of:**") < body.index("## Individual - TOD")


def test_convert_result_exposes_as_of_and_totals(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True, contract=contract)
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.portfolio_totals == [("Total Current Value", "$100,000.00")]


def test_headers_disabled(fixture_csv_path, contract, tmp_path):
    disabled = replace(contract, summary_header=False, section_header=False)
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=disabled)
    body = result.out_path.read_text(encoding="utf-8")

    assert "**As of:**" not in body
    assert "**Total Current Value:**" not in body
    # Sections are always present, so the file opens with the H2 heading.
    assert body.startswith("## Individual - TOD (X10000001)")
    assert result.as_of is None
    assert result.portfolio_totals == []


def test_summary_header_missing_totals_column_skipped(fixture_csv_path, contract, tmp_path):
    bogus = replace(contract, portfolio_totals=(Total(label="Bogus", column="NotARealColumn"),))
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True, contract=bogus)
    # As-of still extracted; bogus portfolio total skipped, none emitted.
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.portfolio_totals == []


def test_vti_appears_twice_in_position_pairs(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True, contract=contract)
    vti_count = next(
        count for (sym, _), count in result.position_pairs.items() if sym == "VTI"
    )
    assert vti_count == 2


# ---- Multi-account ----

def test_multi_account_sections_emitted(multi_fixture_csv_path, contract, tmp_path):
    result = convert_csv(multi_fixture_csv_path, tmp_path, dry_run=False, contract=contract)
    body = result.out_path.read_text(encoding="utf-8")

    assert len(result.accounts) == 3
    assert "## Brokerage - TOD (ACCT-AAA)" in body
    assert "## Rollover IRA (ACCT-BBB)" in body
    assert "## 401(k) Plan (ACCT-CCC)" in body
    # Portfolio total sums Current value across all three accounts.
    assert "**Total Current Value:** $115,000.00" in body
    # First-seen account order is preserved (index lists AAA, then BBB, then CCC).
    assert body.index("ACCT-AAA") < body.index("ACCT-BBB") < body.index("ACCT-CCC")


def test_per_account_subtotals(multi_fixture_csv_path, contract, tmp_path):
    result = convert_csv(multi_fixture_csv_path, tmp_path, dry_run=True, contract=contract)
    totals = {s.account_number: dict(s.totals) for s in result.accounts}
    assert totals["ACCT-AAA"]["Total Current Value"] == "$40,000.00"
    assert totals["ACCT-BBB"]["Total Current Value"] == "$50,000.00"
    assert totals["ACCT-CCC"]["Total Current Value"] == "$25,000.00"


def test_account_index_lists_all_accounts(multi_fixture_csv_path, contract, tmp_path):
    result = convert_csv(multi_fixture_csv_path, tmp_path, dry_run=False, contract=contract)
    body = result.out_path.read_text(encoding="utf-8")
    assert "**Accounts:**" in body
    assert "- Brokerage - TOD (ACCT-AAA): $40,000.00" in body
    assert "- Rollover IRA (ACCT-BBB): $50,000.00" in body
    assert "- 401(k) Plan (ACCT-CCC): $25,000.00" in body


def test_one_bad_account_aborts(multi_fixture_df, contract, write_csv, tmp_path):
    df = multi_fixture_df.copy()
    # Blank the Account Name on the BBB account only — fail-fast aborts the file.
    df.loc[df["Account Number"] == "ACCT-BBB", "Account Name"] = ""
    csv = write_csv(df, "bad_account.csv")

    with pytest.raises(AssertionError, match="Account Name is empty for account ACCT-BBB"):
        convert_csv(csv, tmp_path, dry_run=True, contract=contract)


def test_empty_symbol_account_tolerated(multi_fixture_csv_path, contract, tmp_path):
    result = convert_csv(multi_fixture_csv_path, tmp_path, dry_run=False, contract=contract)
    body = result.out_path.read_text(encoding="utf-8")
    ccc = next(s for s in result.accounts if s.account_number == "ACCT-CCC")
    # The 401(k)-style holding has an empty Symbol but a Current value — it counts.
    assert ccc.positions == 1
    assert "TARGET DATE 2040 FUND" in body


# ---- Validation (global checks) ----

def test_collision_rejected(fixture_csv_path, contract, tmp_path):
    convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=contract)

    with pytest.raises(AssertionError, match="output collision"):
        convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=contract)


def test_missing_required_column_rejected(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.drop(columns=["Account Name"])
    csv = write_csv(df, "no_account_name.csv")

    with pytest.raises(AssertionError, match="required column missing: 'Account Name'"):
        convert_csv(csv, tmp_path, dry_run=True, contract=contract)


def test_missing_symbol_column_rejected(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.drop(columns=["Symbol"])
    csv = write_csv(df, "no_symbol.csv")

    with pytest.raises(AssertionError, match="required column missing: 'Symbol'"):
        convert_csv(csv, tmp_path, dry_run=True, contract=contract)


def test_empty_after_cleanup(fixture_df, contract, write_csv, tmp_path):
    # Replace every data row's Account Number with the drop_rows pattern.
    df = fixture_df.copy()
    df["Account Number"] = "Date downloaded"
    csv = write_csv(df, "all_dropped.csv")

    with pytest.raises(AssertionError, match="no rows after cleanup"):
        convert_csv(csv, tmp_path, dry_run=True, contract=contract)


def test_positions_lost_during_cleanup(fixture_df, contract, write_csv, tmp_path):
    # Force a legitimate position row to match the drop_rows regex.
    df = fixture_df.copy()
    df.loc[0, "Account Number"] = "Date downloaded"
    csv = write_csv(df, "position_lost.csv")

    with pytest.raises(AssertionError, match="positions lost during cleanup"):
        convert_csv(csv, tmp_path, dry_run=True, contract=contract)


def test_column_aliases_applied(fixture_df, contract, write_csv, tmp_path):
    df = fixture_df.rename(columns={"Symbol": "Ticker"})
    csv = write_csv(df, "aliased.csv")

    aliased_contract = replace(contract, column_aliases={"Ticker": "Symbol"})

    result = convert_csv(csv, tmp_path, dry_run=True, contract=aliased_contract)
    assert result.accounts[0].positions == 6


def test_drop_columns_removes_columns(fixture_csv_path, contract, tmp_path):
    dropped_contract = replace(contract, drop_columns=("Sector", "Industry"))

    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=dropped_contract)
    headers = _headers(result)
    assert "Sector" not in headers
    assert "Industry" not in headers
    # Sibling columns like "Industry group" should still be present
    assert "Industry group" in headers


def test_numeric_strings_preserved_verbatim(fixture_df, contract, write_csv, tmp_path):
    # tabulate's numparse would rewrite "1.50" -> "1.5" and "0.000" -> "0".
    df = fixture_df.copy()
    df["Quantity"] = "1.50"
    df.loc[1, "Quantity"] = "0.000"
    csv = write_csv(df, "numeric_strings.csv")

    result = convert_csv(csv, tmp_path, dry_run=False, contract=contract)
    cells = [c for line in _table_lines(result) for c in _split_row(line)]
    assert "1.50" in cells
    assert "0.000" in cells


def _write_raw_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return path


def _table_lines(result):
    return [l for l in result.out_path.read_text(encoding="utf-8").splitlines() if l.startswith("|")]


def _split_row(line):
    return [c.strip() for c in line.strip("|").split("|")]


def _headers(result):
    return _split_row(_table_lines(result)[0])


def test_duplicate_headers_preserved_verbatim(tmp_path):
    # Fidelity repeats some headers; they must not be mangled to "Change $.1".
    path = _write_raw_csv(tmp_path / "dup.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value", "Change $", "Change $"],
        ["X1", "Brokerage", "VTI", "$100.00", "+$1.00", "+$2.00"],
    ])
    result = convert_csv(path, tmp_path, dry_run=False, contract=replace(CONTRACT, drop_duplicate_columns=False))
    assert _headers(result).count("Change $") == 2
    assert "Change $.1" not in _table_lines(result)[0]


def test_duplicated_required_column_rejected(tmp_path):
    path = _write_raw_csv(tmp_path / "dup_required.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value", "Current value"],
        ["X1", "Brokerage", "VTI", "$100.00", "$100.00"],
    ])
    # With dedup on, an identical copy is simply dropped; the guard covers dedup off.
    with pytest.raises(AssertionError, match="required column duplicated: 'Current value'"):
        convert_csv(path, tmp_path, dry_run=True, contract=replace(CONTRACT, drop_duplicate_columns=False))


def test_trailing_comma_rows_and_short_footer_rows(tmp_path):
    # Data rows one field wider than the header; footer rows a single field.
    path = _write_raw_csv(tmp_path / "ragged.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value"],
        ["X1", "Brokerage", "VTI", "$100.00", ""],
        ["Date downloaded Apr-03-2026 12:01 p.m ET"],
    ])
    result = convert_csv(path, tmp_path, dry_run=True)
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.rows == 1
    assert result.cols == 4


# ---- Duplicate columns ----

def test_identical_duplicate_columns_dropped(fixture_csv_path, contract, tmp_path):
    # The fixture's appended summary block repeats 8 headers, some differing only
    # by leading space or case ("Last price" / "Last Price"); values all match.
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False, contract=contract)
    headers = _headers(result)
    assert result.cols == 41
    assert len(result.dropped_duplicates) == 8
    assert len({h.casefold() for h in headers}) == len(headers)
    # First occurrence kept, verbatim.
    assert "Last price" in headers and "Last Price" not in headers


def test_duplicate_column_mismatch_aborts(tmp_path):
    path = _write_raw_csv(tmp_path / "dup_mismatch.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value", "Change $", " Change $"],
        ["X1", "Brokerage", "VTI", "$100.00", "+$1.00", "+$1.00"],
        ["X1", "Brokerage", "AAPL", "$50.00", "+$2.00", "+$9.99"],
    ])
    with pytest.raises(AssertionError, match=r"duplicate column ' Change \$' differs from 'Change \$' at Symbol 'AAPL'"):
        convert_csv(path, tmp_path, dry_run=True)


def test_duplicate_columns_kept_when_disabled(fixture_csv_path, contract, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True,
                         contract=replace(contract, drop_duplicate_columns=False))
    assert result.cols == 49
    assert result.dropped_duplicates == []


def test_identical_duplicate_required_columns_accepted(tmp_path):
    # Repeated required columns must be deduped before label-based access:
    # otherwise df["Current value"] is a DataFrame (bogus loss baseline) and
    # df["Account Number"].str fails. Footer rows must not count as mismatches.
    footer = ["Date downloaded Aug-07-2026 2:44 p.m ET"]
    for extra, value in (("Current value", "$100.00"), ("Account Number", "X1")):
        path = _write_raw_csv(tmp_path / f"dup_{extra}.csv", [
            ["Account Number", "Account Name", "Symbol", "Current value", extra],
            ["X1", "Brokerage", "VTI", "$100.00", value],
            footer,
        ])
        result = convert_csv(path, tmp_path, dry_run=True)
        assert result.cols == 4
        assert result.dropped_duplicates == [extra]
        assert result.accounts[0].positions == 1
        assert result.as_of == "Aug-07-2026 2:44 p.m ET"


def test_duplicated_account_number_rejected_when_dedup_off(tmp_path):
    # The guard runs before drop_rows' .str access, so this is a clear
    # AssertionError rather than an AttributeError.
    path = _write_raw_csv(tmp_path / "dup_acct.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value", "Account Number"],
        ["X1", "Brokerage", "VTI", "$100.00", "X1"],
    ])
    with pytest.raises(AssertionError, match="required column duplicated: 'Account Number'"):
        convert_csv(path, tmp_path, dry_run=True, contract=replace(CONTRACT, drop_duplicate_columns=False))


# ---- Review fixes (v4.1.0) ----

def test_wide_row_with_data_aborts(tmp_path):
    # Trailing empty fields are tolerated (see test_trailing_comma_rows...),
    # but a non-empty surplus field would be silently lost.
    path = _write_raw_csv(tmp_path / "wide.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value"],
        ["X1", "Brokerage", "VTI", "$100.00", "LOST"],
    ])
    with pytest.raises(AssertionError, match=r"CSV row 2 has 5 fields but the header has 4.*'LOST'"):
        convert_csv(path, tmp_path, dry_run=True)


def test_pipe_and_newline_cannot_break_table(tmp_path):
    path = _write_raw_csv(tmp_path / "pipes.csv", [
        ["Account Number", "Account Name", "Symbol", "Description", "Current value"],
        ["X1", "Brokerage", "VTI", "A | B\nC", "$100.00"],
    ])
    result = convert_csv(path, tmp_path, dry_run=False)
    table = _table_lines(result)
    assert len(table) == 3  # header, separator, one data row
    assert r"A \| B C" in table[2]
    # Every line has the same number of unescaped cell separators.
    assert len({len(re.findall(r"(?<!\\)\|", l)) for l in table}) == 1


def test_drop_columns_on_deduplicated_column(fixture_csv_path, tmp_path):
    # "Last price" has a removed duplicate ("Last Price"); dropping it must not
    # crash the duplicate verification.
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=True,
                         contract=replace(CONTRACT, drop_columns=("Last price",)))
    assert result.cols == 40


def test_unparseable_total_cell_warns_and_is_excluded(tmp_path, capsys):
    path = _write_raw_csv(tmp_path / "bad_value.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value"],
        ["X1", "Brokerage", "VTI", "$100.00"],
        ["X1", "Brokerage", "AAPL", "n/a*"],
        ["X1", "Brokerage", "CASH", "--"],
    ])
    result = convert_csv(path, tmp_path, dry_run=True)
    assert result.portfolio_totals == [("Total Current Value", "$100.00")]
    err = capsys.readouterr().err
    # Reported once (not once per account/index/portfolio), naming the cell;
    # the '--' sentinel is not reported.
    assert err.count("unparseable cell") == 1
    assert "'n/a*'" in err and "'--'" not in err


def test_totals_are_exact_and_never_negative_zero(tmp_path):
    path = _write_raw_csv(tmp_path / "exact.csv", [
        ["Account Number", "Account Name", "Symbol", "Current value"],
        ["X1", "Brokerage", "A", "$0.30"],
        ["X1", "Brokerage", "B", "-$0.10"],
        ["X1", "Brokerage", "C", "($0.20)"],
    ])
    result = convert_csv(path, tmp_path, dry_run=True)
    assert result.portfolio_totals == [("Total Current Value", "$0.00")]


def test_footer_removed_when_account_number_is_not_first(tmp_path):
    # Fidelity writes the footer as a one-field row, so its text lands in the
    # first column — here Symbol, not Account Number. The marker matches anywhere.
    path = _write_raw_csv(tmp_path / "reordered.csv", [
        ["Symbol", "Account Number", "Account Name", "Current value"],
        ["VTI", "X1", "Brokerage", "$100.00"],
        ["Date downloaded Apr-03-2026 12:01 p.m ET"],
    ])
    result = convert_csv(path, tmp_path, dry_run=True)
    assert result.as_of == "Apr-03-2026 12:01 p.m ET"
    assert result.rows == 1


def test_account_index_follows_heading_template(fixture_csv_path, tmp_path):
    result = convert_csv(fixture_csv_path, tmp_path, dry_run=False,
                         contract=replace(CONTRACT, heading_template="{Account Name}"))
    body = result.out_path.read_text(encoding="utf-8")
    assert "## Individual - TOD\n" in body
    assert "- Individual - TOD: $100,000.00" in body


def test_fixture_df_keeps_verbatim_headers(fixture_df):
    # Fixtures load like the script reads: no ".1" mangling, no NaN.
    assert list(fixture_df.columns).count("Total gain/loss $") == 2
    assert not any(c.endswith(".1") for c in fixture_df.columns)
    assert not fixture_df.isna().any().any()
