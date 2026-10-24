#!/usr/bin/env python3
"""
fidelity_csv_to_markdown

Version: 3.0.0
Date: 2026-06-06

Changelog:
- v3.0.0 (2026-06-06)
  - Multi-account: a CSV is now grouped by Account Number and rendered as one
    markdown file with a "## <Account Name> (<Account Number>)" section per
    account. A single-account export is simply the N=1 case — there is one
    uniform code path. This REVERSES v2.2.0's multi-account rejection: an
    "All Accounts" Fidelity export is now consumed directly rather than aborted.
  - Output filename now derives from the input CSV stem (e.g.
    Portfolio_Positions_Jun-06-2026.md), for every account count. The previous
    "<account_name>__<account_number>.md" naming is retired. (Breaking change.)
  - Header redesign: the file opens with an always-emitted portfolio header —
    "**As of:**", a portfolio "**Total Current Value:**" (sum of Current value
    across ALL accounts), and an account index listing each account with its
    subtotal — followed by per-account sections, each carrying its own subtotal.
    All sums are plain single-column aggregations (CLAUDE.md carve-out); no
    ratios or percentages-of-portfolio. Driven by the contract's
    output.markdown.summary_header (portfolio), .section_header (per account),
    .sections (grouping), and .account_index blocks.
  - Positions-loss detection now runs across all accounts (global Counter).
    convert_csv returns a reshaped ConvertResult: per-account AccountSection
    records plus portfolio-level as_of/portfolio_totals.
  - Removed the now-unused normalize_account_name / normalize_account_number
    filename helpers.
  - Validate the contract at load time (validate_contract): unknown keys, wrong
    types, and uncompilable regexes in the behavior-bearing subtrees now abort
    with a list of problems instead of silently degrading to default behavior.
- v2.3.0 (2026-05-21)
  - Emit a contract-driven summary header above the markdown table: an
    "**As of:** <timestamp>" line extracted from the Fidelity "Date downloaded"
    footer, plus one "**<label>:** $X,XXX.XX" line per configured total
    (default: Total Current Value). Driven by output.markdown.summary_header
    in the YAML contract; set enabled: false to suppress. Summing one column
    verbatim is treated as formatting under CLAUDE.md's aggregation carve-out.
  - ConvertResult gains as_of and totals fields; --verbose prints both.
- v2.2.0 (2026-05-20)
  - Reject multi-account CSVs: abort with a clear error if a single CSV
    contains positions for more than one Account Number (previously mis-labeled
    the output from row 0). [Reversed in v3.0.0.]
  - Reject output filename collisions: abort if the computed output path
    already exists (previously silently overwrote).
  - --verbose and --quiet are now mutually exclusive at argparse level (was a
    silent override of --verbose by --quiet).
  - --csvdir glob is case-insensitive: matches Positions.CSV / Export.Csv.
  - Reformatted argparse error output: blank-line-separated ERROR + two-line
    usage hint + pointer to --help. --help output is unchanged.
  - Standardized validation failures on AssertionError; required-column checks
    previously raised KeyError.
  - convert_csv now returns a ConvertResult dataclass instead of a dict.
  - Internal: _position_pairs helper hoists per-row norm_str calls; _bar no
    longer renders a stray '>' on the empty first frame; assorted no-op
    cleanups (dead A-Z in normalize_account_number, redundant .astype(str)
    calls, unused prefix parameter on print helpers).
- v2.1.0 (2026-04-18)
  - Output modes redesigned: default is brief one-line summary; --verbose for
    full detail block; --quiet suppresses all stdout (errors only on stderr).
  - Animated progress bar in default batch mode (was --quiet).
- v2.0.0 (2026-04-18)
  - Add --csvdir for batch mode: process all CSVs in a directory.
  - Add --dry-run: validate and report without writing files.
  - Add --quiet: one-line summary per file; animated progress bar in batch.
  - Progress display in batch mode: [n/total] prefix in verbose mode.
  - Cleaner verification output with named check results.
  - Verification failures now report the specific check that failed.
  - Contract: support drop_columns list in input_cleanup.
  - Contract: support column_aliases map in input_cleanup.
- v1.1.0 (2026-03-26)
  - Guard against df.to_markdown() returning None; raise AssertionError on empty output.
  - Save pre-cleanup position pairs and diff against post-cleanup to catch positions
    silently dropped by footer or drop_rows rules.
  - Warn to stderr when a contract drop rule references a column absent from the CSV.
- v1.0.0 (2026-03-26)
  - Derived from fidelity_csv_to_parquet v1.1.3.
  - Replaced Parquet output with a single markdown table.
  - Removed lossless/optimized layer concept; all original columns preserved as-is.
  - Removed companion column derivation (__usd, __pct) and pyarrow dependency.
  - Verification moved to pre-write in-memory checks against the cleaned DataFrame.

Description:
Converts Fidelity positions CSV exports into markdown using a YAML contract for
cleanup, validation, and output policy. The CSV is grouped by Account Number and
rendered as one file with a portfolio header followed by a section per account.
All original columns and string values are preserved without modification
(unless drop_columns is specified in the contract).
"""

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
import re
import sys
from pathlib import Path

import pandas as pd

__version__ = "4.0.0"


# ================================
# Helpers
# ================================

def norm_str(val: object) -> str:
    return "" if pd.isna(val) else str(val).strip()


def _position_pairs(symbols, values) -> Counter:
    pairs = [(norm_str(s), norm_str(v)) for s, v in zip(symbols, values)]
    return Counter(p for p in pairs if any(p))


def _bar(current: int, total: int, width: int = 28) -> str:
    filled = round(width * current / total) if total else width
    if filled == 0:
        bar = " " * width
    else:
        head = "=" if filled >= width else ">"
        bar = "=" * (filled - 1) + head + " " * (width - filled)
    return f"[{bar}] {current}/{total}"


def _size_str(path: Path) -> str:
    size = path.stat().st_size
    return f"{size / 1024:.1f}KB" if size >= 1024 else f"{size}B"


def _parse_currency(val: object) -> float | None:
    """Parse strings like '$1,234.56', '-$1,234.56', '($1,234.56)' to float. Returns None if unparseable or sentinel."""
    s = norm_str(val)
    if not s or s == "--":
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True
    s = s.replace("$", "").replace(",", "").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negative else v


def _format_usd(amount: float) -> str:
    if amount < 0:
        return f"-${-amount:,.2f}"
    return f"${amount:,.2f}"


def _extract_as_of(df: pd.DataFrame, pattern: str) -> str | None:
    """Search every cell for the regex; return the first capture group's match."""
    compiled = re.compile(pattern, re.IGNORECASE)
    for col in df.columns:
        series = df[col].dropna().astype(str)
        for val in series:
            m = compiled.search(val)
            if m:
                return (m.group(1) if m.groups() else m.group(0)).strip()
    return None


def _compute_totals(df: pd.DataFrame, totals_cfg: "tuple[Total, ...]") -> list[tuple[str, str]]:
    """Sum each configured column verbatim and format as USD.

    Plain pass-through aggregation (CLAUDE.md carve-out) — one column summed,
    no ratios or derived values. Unparseable cells ('--', blank) are skipped; a
    missing column logs a warning and yields no line.
    """
    totals: list[tuple[str, str]] = []
    for entry in totals_cfg:
        label, col = entry.label, entry.column
        if col not in df.columns:
            print(f"WARNING: totals column '{col}' not in CSV — skipped", file=sys.stderr)
            continue
        parsed_values = [v for v in (_parse_currency(x) for x in df[col]) if v is not None]
        if not parsed_values:
            continue
        totals.append((label, _format_usd(sum(parsed_values))))
    return totals


def _format_heading(template: str, row: pd.Series) -> str:
    """Substitute {Column Name} placeholders in a heading template from a row."""
    def repl(m: re.Match) -> str:
        col = m.group(1)
        return norm_str(row[col]) if col in row.index else m.group(0)
    return re.sub(r"\{([^}]+)\}", repl, template)


# ================================
# Contract
# ================================
#
# The contract is the declarative policy for this script: cleanup rules, footer
# detection, sectioning, and which single-column sums to emit. It lives here as
# a frozen dataclass rather than an external file so it is versioned, shipped,
# and invoked together with the code that reads it. A mistyped field name fails
# at import (TypeError) and an invalid regex fails at import (re.error) — no
# separate schema checker needed. To adapt to a new Fidelity layout, edit
# CONTRACT below; the conversion logic should not need to change.

@dataclass(frozen=True)
class Total:
    """One plain single-column sum (CLAUDE.md aggregation carve-out)."""
    label: str
    column: str


@dataclass(frozen=True)
class DropRow:
    column: str
    regex: str


@dataclass(frozen=True)
class Contract:
    # ---- input cleanup ----
    # Renames applied before anything else (absent source columns are ignored).
    column_aliases: dict[str, str]
    # Columns removed from the output entirely.
    drop_columns: tuple[str, ...]
    # Rows whose `column` matches `regex` (re.match) are dropped.
    drop_rows: tuple[DropRow, ...]
    # Case-insensitive substrings marking disclaimer/footer rows for removal.
    # Never use generic brand tokens ("fidelity") — they appear in security names.
    footer_markers: tuple[str, ...]

    # ---- sections ----
    # Column the file is split on; account order is first-seen (no sorting).
    group_by: str
    # Each section's H2 heading, filled from that account's first row.
    heading_template: str

    # ---- portfolio header (top of file) ----
    summary_header: bool
    # Case-insensitive regex searched across all cells *before* drop_rows; the
    # first capture group is emitted verbatim as "As of:". Missing is non-fatal.
    as_of_pattern: str | None
    # Each sums one column across ALL accounts.
    portfolio_totals: tuple[Total, ...]
    # One "- <name> (<number>): $X" line per account (sum of account_index_column).
    account_index: bool
    account_index_label: str
    account_index_column: str

    # ---- per-account subtotal under each section heading ----
    section_header: bool
    section_totals: tuple[Total, ...]

    def __post_init__(self) -> None:
        # Fail at import, not mid-run, on an uncompilable pattern.
        for rule in self.drop_rows:
            re.compile(rule.regex)
        if self.as_of_pattern:
            re.compile(self.as_of_pattern)


CONTRACT = Contract(
    # Fidelity's "My View" export lowercases the second word of the account
    # columns vs. the "Positions" export. Normalize to the canonical names the
    # required-column check expects.
    column_aliases={
        "Account number": "Account Number",
        "Account name": "Account Name",
    },
    drop_columns=(),
    drop_rows=(DropRow(column="Account Number", regex="Date downloaded"),),
    footer_markers=(
        "the data and information in this spreadsheet",
        "brokerage services are provided by fidelity brokerage",
        "for informational purposes only",
        "fidelity.com",
    ),
    group_by="Account Number",
    heading_template="{Account Name} ({Account Number})",
    summary_header=True,
    as_of_pattern=r"Date downloaded\s+(.+)",
    portfolio_totals=(Total(label="Total Current Value", column="Current value"),),
    account_index=True,
    account_index_label="Accounts",
    account_index_column="Current value",
    section_header=True,
    section_totals=(Total(label="Total Current Value", column="Current value"),),
)


# ================================
# Core conversion
# ================================

@dataclass
class AccountSection:
    account_name: str
    account_number: str
    rows: int
    positions: int
    position_pairs: Counter
    totals: list[tuple[str, str]]


@dataclass
class ConvertResult:
    out_path: Path
    as_of: str | None
    portfolio_totals: list[tuple[str, str]]
    accounts: list[AccountSection]
    rows: int
    cols: int
    position_pairs: Counter
    size: str
    version: str
    dry_run: bool


def _load_and_clean(csv_path: Path, contract: Contract) -> tuple[pd.DataFrame, str | None, Counter]:
    """Read, alias, extract as_of, drop rows/columns, strip footers, and verify
    column/required-column integrity. Returns (cleaned df, as_of, raw position
    pairs captured before cleanup for loss detection).
    """
    # keep_default_na=False: empty cells stay empty strings rather than float
    # NaN. Without it, blank source cells render as the literal "nan" in the
    # markdown — a string-preservation violation that injects a phantom value
    # (see CLAUDE.md "String preservation is intentional"). Fidelity uses "--"
    # for N/A (already a literal string) and blank for empty; nothing in the
    # data relies on NaN coercion.
    #
    # Fidelity occasionally emits a trailing comma on every data row, giving
    # data rows one more field than the header. Detect and strip the surplus
    # trailing fields before pandas sees the data so it never raises a
    # ParserWarning. Uses csv.reader to handle quoted cells correctly, then
    # writes a normalised in-memory CSV for pandas to consume.
    with open(csv_path, encoding="utf-8-sig", newline="") as _f:
        _rows = list(csv.reader(_f))
    _header_len = len(_rows[0]) if _rows else 0
    _n_max = max((len(r) for r in _rows if r), default=_header_len)
    if _n_max > _header_len:
        import io as _io
        _buf = _io.StringIO()
        _writer = csv.writer(_buf)
        for _row in _rows:
            _writer.writerow(_row[:_header_len])
        _buf.seek(0)
        df = pd.read_csv(_buf, dtype=str, index_col=False, keep_default_na=False)
    else:
        df = pd.read_csv(csv_path, dtype=str, index_col=False, encoding="utf-8-sig",
                         keep_default_na=False)

    # Apply column aliases before anything else
    if contract.column_aliases:
        df = df.rename(columns=contract.column_aliases)

    aliased_columns = list(df.columns)

    # Baseline position pairs for loss detection
    raw_position_pairs: Counter = Counter()
    if "Symbol" in df.columns and "Current value" in df.columns:
        raw_position_pairs = _position_pairs(df["Symbol"], df["Current value"])

    # Extract "As of" timestamp BEFORE drop_rows strips it. The Fidelity
    # "Date downloaded ..." footer is otherwise lost to cleanup.
    as_of: str | None = None
    if contract.summary_header and contract.as_of_pattern:
        as_of = _extract_as_of(df, contract.as_of_pattern)

    # Drop rows per contract
    for rule in contract.drop_rows:
        if rule.column not in df.columns:
            print(f"WARNING: drop_rows column '{rule.column}' not in CSV — skipped", file=sys.stderr)
            continue
        df = df[~df[rule.column].str.match(rule.regex, na=False)]

    # Drop columns per contract
    drop_cols = contract.drop_columns
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
        else:
            print(f"WARNING: drop_columns entry '{col}' not in CSV — skipped", file=sys.stderr)

    # Footer/disclaimer removal (skip on empty df: agg+axis=1 on zero rows
    # returns a DataFrame instead of a Series in pandas 3.x and crashes the
    # .str accessor)
    if contract.footer_markers and not df.empty:
        markers_lc = [m.lower() for m in contract.footer_markers if m.strip()]
        if markers_lc:
            row_text = df.fillna("").agg(" | ".join, axis=1).str.lower()
            pattern = "|".join(re.escape(m) for m in markers_lc)
            df = df[~row_text.str.contains(pattern, regex=True, na=False)]

    # ---- Verification ----
    expected_cols = [c for c in aliased_columns if c not in drop_cols]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise AssertionError(f"FAIL columns unexpectedly dropped: {missing}")

    for col in ("Account Name", "Account Number", "Symbol", "Current value"):
        if col not in df.columns:
            raise AssertionError(f"FAIL required column missing: '{col}'")

    if len(df) == 0:
        raise AssertionError("FAIL no rows after cleanup — check drop rules and footer markers")

    return df, as_of, raw_position_pairs


def _render_section(df_account: pd.DataFrame, contract: Contract) -> tuple[str, AccountSection]:
    """Validate one account group and render its markdown section. Fail-fast:
    any invalid account aborts the whole file."""
    acct_name_raw = norm_str(df_account["Account Name"].iloc[0])
    acct_num_raw = norm_str(df_account["Account Number"].iloc[0])

    if not acct_num_raw:
        raise AssertionError("FAIL Account Number is empty for a section")
    if not acct_name_raw:
        raise AssertionError(f"FAIL Account Name is empty for account {acct_num_raw}")

    # Tolerates an empty Symbol when Current value is present (e.g. a 401(k)
    # custom fund) — _position_pairs keeps a pair if either field is non-empty.
    position_pairs = _position_pairs(df_account["Symbol"], df_account["Current value"])
    if not position_pairs:
        raise AssertionError(f"FAIL no valid symbol/value pairs for account {acct_num_raw}")

    heading = _format_heading(contract.heading_template, df_account.iloc[0])

    totals: list[tuple[str, str]] = []
    if contract.section_header:
        totals = _compute_totals(df_account, contract.section_totals)

    # disable_numparse: tabulate otherwise reformats numeric-looking strings
    # ("1.50" -> "1.5", "0.000" -> "0") — a string-preservation violation.
    table = df_account.to_markdown(index=False, disable_numparse=True)
    if not table:
        raise AssertionError(f"FAIL markdown serialization produced no output for account {acct_num_raw}")

    lines = [f"## {heading}", ""]
    for label, value in totals:
        lines.append(f"**{label}:** {value}")
    if totals:
        lines.append("")
    lines.append(table)

    section = AccountSection(
        account_name=acct_name_raw,
        account_number=acct_num_raw,
        rows=len(df_account),
        positions=len(position_pairs),
        position_pairs=position_pairs,
        totals=totals,
    )
    return "\n".join(lines), section


def convert_csv(csv_path: Path, out_dir: Path, dry_run: bool, contract: Contract = CONTRACT) -> ConvertResult:
    """
    Convert one CSV to a sectioned markdown file (one section per account).
    Raises on failure. Does not print anything.
    """
    df, as_of, raw_position_pairs = _load_and_clean(csv_path, contract)

    header_enabled = contract.summary_header
    index_enabled = header_enabled and contract.account_index
    index_total_col = contract.account_index_column

    # Group by account, preserving first-seen order (sort=False).
    sections_md: list[str] = []
    accounts: list[AccountSection] = []
    combined_pairs: Counter = Counter()
    index_lines: list[str] = []

    for _, group in df.groupby(contract.group_by, sort=False):
        section_md, section = _render_section(group, contract)
        sections_md.append(section_md)
        accounts.append(section)
        combined_pairs.update(section.position_pairs)

        if index_enabled:
            total_str = ""
            if index_total_col and index_total_col in group.columns:
                vals = [v for v in (_parse_currency(x) for x in group[index_total_col]) if v is not None]
                if vals:
                    total_str = _format_usd(sum(vals))
            suffix = f": {total_str}" if total_str else ""
            index_lines.append(f"- {section.account_name} ({section.account_number}){suffix}")

    # ---- Global positions-loss check (across all accounts) ----
    if raw_position_pairs:
        lost = raw_position_pairs - combined_pairs
        if lost:
            raise AssertionError(f"FAIL positions lost during cleanup: {dict(lost)}")

    # ---- Portfolio header (always emitted when enabled) ----
    portfolio_totals: list[tuple[str, str]] = []
    header_lines: list[str] = []
    if header_enabled:
        portfolio_totals = _compute_totals(df, contract.portfolio_totals)
        if as_of:
            header_lines.append(f"**As of:** {as_of}")
        for label, value in portfolio_totals:
            header_lines.append(f"**{label}:** {value}")
        if index_enabled and index_lines:
            if header_lines:
                header_lines.append("")
            header_lines.append(f"**{contract.account_index_label}:**")
            header_lines.extend(index_lines)

    # ---- Compose ----
    body = "\n\n".join(sections_md)
    markdown = "\n".join(header_lines) + "\n\n" + body if header_lines else body

    # Output filename derives from the input CSV stem (every account count).
    out_path = out_dir / f"{csv_path.stem}.md"
    if out_path.exists():
        raise AssertionError(
            f"FAIL output collision: {out_path} already exists. "
            "Remove the existing file or choose a different --outdir."
        )

    if not dry_run:
        out_path.write_text(markdown, encoding="utf-8")
        size = _size_str(out_path)
    else:
        size = "dry-run"

    return ConvertResult(
        out_path=out_path,
        as_of=as_of,
        portfolio_totals=portfolio_totals,
        accounts=accounts,
        rows=len(df),
        cols=len(df.columns),
        position_pairs=combined_pairs,
        size=size,
        version=__version__,
        dry_run=dry_run,
    )


# ================================
# Output formatting
# ================================

def print_result_verbose(r: ConvertResult) -> None:
    print(f"=== {r.out_path.name} ===")
    print(f"accounts  {len(r.accounts)}  rows  {r.rows}  cols  {r.cols}  size  {r.size}")
    print(f"version   {r.version}")
    if r.as_of:
        print(f"as of     {r.as_of}")
    for label, value in r.portfolio_totals:
        print(f"{label.lower()}  {value}")
    tag = " [dry-run]" if r.dry_run else ""
    print(f"checks    ✓ columns intact  ✓ no losses{tag}")
    print()
    for section in r.accounts:
        print(f"## {section.account_name} ({section.account_number})  rows={section.rows} pos={section.positions}")
        for label, value in section.totals:
            print(f"   {label}: {value}")
        for (sym, val), count in sorted(section.position_pairs.items()):
            suffix = f" (x{count})" if count > 1 else ""
            print(f"   {sym:<12} {val}{suffix}")
        print()


def print_result_quiet(r: ConvertResult) -> None:
    tag = " [dry-run]" if r.dry_run else ""
    total_positions = sum(s.positions for s in r.accounts)
    print(
        f"✓ {r.out_path.name}"
        f"  accounts={len(r.accounts)} rows={r.rows} pos={total_positions} size={r.size}{tag}"
    )


# ================================
# Main
# ================================

class _FormattedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        prog = self.prog
        sys.stderr.write(f"\nERROR: {message}\n\n")
        sys.stderr.write("Usage:\n")
        sys.stderr.write(f"  {prog} --csv FILE [options]\n")
        sys.stderr.write(f"  {prog} --csvdir DIR [options]\n\n")
        sys.stderr.write(f"Run '{prog} --help' for the full option list.\n")
        sys.exit(2)


def main():
    parser = _FormattedArgumentParser(
        description="Convert Fidelity positions CSV(s) to Markdown"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Single input Fidelity positions CSV")
    source.add_argument("--csvdir", help="Directory of CSVs to process in batch")
    parser.add_argument("--outdir", help="Output directory (default: alongside each input file)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument("--verbose", action="store_true", help="Detailed block output per file")
    output_mode.add_argument("--quiet", action="store_true", help="Suppress all output except errors")

    args = parser.parse_args()

    # Build file list
    if args.csv:
        p = Path(args.csv).expanduser().resolve()
        if not p.exists():
            print(f"ERROR: CSV not found: {p}", file=sys.stderr)
            sys.exit(1)
        csv_files = [p]
    else:
        d = Path(args.csvdir).expanduser().resolve()
        if not d.is_dir():
            print(f"ERROR: not a directory: {d}", file=sys.stderr)
            sys.exit(1)
        csv_files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
        if not csv_files:
            print(f"ERROR: no CSV files found in {d}", file=sys.stderr)
            sys.exit(1)

    def out_dir_for(csv_path: Path) -> Path:
        if args.outdir:
            return Path(args.outdir).expanduser().resolve()
        return csv_path.parent

    total = len(csv_files)
    batch = total > 1
    errors = []

    for i, csv_path in enumerate(csv_files, 1):
        out_dir = out_dir_for(csv_path)
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)

        if batch and not args.quiet and not args.verbose:
            sys.stdout.write(f"\r{_bar(i, total)}  {csv_path.name:<40}")
            sys.stdout.flush()

        try:
            result = convert_csv(csv_path, out_dir, args.dry_run)

            if args.quiet:
                pass
            elif args.verbose:
                if batch:
                    print(f"\n[{i}/{total}] {csv_path.name}")
                print_result_verbose(result)
            else:
                if batch:
                    sys.stdout.write("\n")
                print_result_quiet(result)

        except Exception as exc:
            if batch and not args.quiet and not args.verbose:
                sys.stdout.write("\n")
            elif batch and args.verbose:
                print(f"\n[{i}/{total}] {csv_path.name}")
            print(f"✗ {csv_path.name}: {exc}", file=sys.stderr)
            errors.append(csv_path.name)

    if batch and not args.quiet:
        print()
        ok = total - len(errors)
        if errors:
            print(f"Done: {ok}/{total} succeeded  failed: {errors}", file=sys.stderr)
        else:
            print(f"Done: {ok}/{total} succeeded")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
