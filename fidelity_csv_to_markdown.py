#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
fidelity_csv_to_markdown

Converts Fidelity "Positions" CSV exports into LLM-ready markdown. The CSV is
grouped by Account Number and rendered as one file with a portfolio header
followed by a section per account. All original columns and string values are
preserved verbatim (unless CONTRACT.drop_columns says otherwise). Cleanup and
output policy live in the inline CONTRACT below. History is in CHANGELOG.md.
"""

import argparse
import csv
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
import types
from typing import get_args, get_origin

__version__ = "5.0.0"

REQUIRED_COLUMNS = ("Account Name", "Account Number", "Symbol", "Current value")


# ================================
# Helpers
# ================================

def norm_str(val: str) -> str:
    return val.strip()


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


_SENTINELS = ("", "--")


def _parse_currency(val: str) -> Decimal | None:
    """Parse '$1,234.56', '-$1,234.56', '+$1.00', '($1,234.56)' exactly.
    Returns None for the blank/'--' sentinels; raises ValueError otherwise."""
    s = norm_str(val)
    if s in _SENTINELS:
        return None
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "").strip()
    try:
        v = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"unparseable currency value {val!r}") from None
    if not v.is_finite():
        raise ValueError(f"unparseable currency value {val!r}")
    return -v if negative else v


def _format_usd(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"))
    if amount == 0:
        amount = Decimal("0.00")  # never print "-$0.00"
    if amount < 0:
        return f"-${-amount:,.2f}"
    return f"${amount:,.2f}"


def _extract_as_of(cells: Iterable[str], pattern: str) -> str | None:
    """Search the cells in order; return the first match's capture group."""
    compiled = re.compile(pattern, re.IGNORECASE)
    for val in cells:
        m = compiled.search(val)
        if m:
            return (m.group(1) if m.groups() else m.group(0)).strip()
    return None


@dataclass
class Table:
    """All-str rows under a header whose names may repeat (with
    drop_duplicate_columns off). Lookups by name take the first occurrence."""
    header: list[str]
    rows: list[list[str]]

    def col(self, name: str) -> list[str]:
        i = self.header.index(name)
        return [r[i] for r in self.rows]


def _sum_column(table: Table, col: str) -> str | None:
    """Sum one column exactly and format as USD — plain pass-through
    aggregation (CLAUDE.md carve-out). Blank/'--' cells and anything
    _warn_on_total_columns already reported are skipped; returns None if the
    column is absent or nothing parses."""
    if col not in table.header:
        return None
    values = []
    for x in table.col(col):
        try:
            v = _parse_currency(x)
        except ValueError:
            continue
        if v is not None:
            values.append(v)
    return _format_usd(sum(values)) if values else None


def _warn_on_total_columns(table: Table, columns: set[str]) -> None:
    """Warn once per totals column that is missing or has cells that are
    neither a currency value nor a blank/'--' sentinel — those are left out of
    every total, so the reader must be told."""
    for col in sorted(columns):
        if col not in table.header:
            print(f"WARNING: totals column '{col}' not in CSV — skipped", file=sys.stderr)
            continue
        bad = []
        for x in table.col(col):
            try:
                _parse_currency(x)
            except ValueError:
                bad.append(norm_str(x))
        if bad:
            print(f"WARNING: {len(bad)} unparseable cell(s) in '{col}' left out of totals: "
                  + ", ".join(repr(b) for b in bad[:5]), file=sys.stderr)


def _compute_totals(table: Table, totals: "tuple[Total, ...]") -> list[tuple[str, str]]:
    """One (label, $amount) pair per configured Total that yields a value."""
    pairs = [(t.label, _sum_column(table, t.column)) for t in totals]
    return [(label, value) for label, value in pairs if value is not None]


def _md_cell(val: str) -> str:
    # The only edit ever made to a value: a literal "|" or line break would
    # split the markdown table, so "|" is escaped and line breaks become spaces.
    return re.sub(r"\r\n|\r|\n", " ", val).replace("|", r"\|")


def _pipe_table(header: list[str], rows: list[list[str]]) -> str:
    """Render a markdown pipe table, byte-for-byte what tabulate's "pipe"
    format with disable_numparse=True produced through v4.1.0: values are
    never reinterpreted, cells (not headers) are stripped, every column is
    left-aligned, and a column is as wide as its widest cell or its header
    plus 2, whichever is larger."""
    rows = [[c.strip() for c in r] for r in rows]
    widths = [max([len(h) + 2] + [len(r[i]) for r in rows]) for i, h in enumerate(header)]

    def line(cells: list[str]) -> str:
        return "|" + "|".join(f" {c.ljust(w)} " for c, w in zip(cells, widths)) + "|"

    separator = "|" + "|".join(":" + "-" * (w + 1) for w in widths) + "|"
    return "\n".join([line(header), separator] + [line(r) for r in rows])


def _format_heading(template: str, header: list[str], row: list[str]) -> str:
    """Substitute {Column Name} placeholders in a heading template from a row."""
    values: dict[str, str] = {}
    for name, val in zip(header, row):
        values.setdefault(name, val)  # first occurrence, like Table.col

    def repl(m: re.Match) -> str:
        col = m.group(1)
        return norm_str(values[col]) if col in values else m.group(0)
    return re.sub(r"\{([^}]+)\}", repl, template)


# ================================
# Contract
# ================================

def _check_type(path: str, value: object, tp: object) -> None:
    """Raise TypeError unless value matches the annotation tp. Handles the
    shapes the contract uses: plain classes, X | None, tuple[X, ...], and
    dict[K, V]. Catches the missing-comma typo ("a") vs ("a",)."""
    origin = get_origin(tp)
    if origin is tuple:
        if not isinstance(value, tuple):
            raise TypeError(f"{path} must be a tuple, got {type(value).__name__} {value!r}"
                            " (a one-element tuple needs a trailing comma)")
        for i, item in enumerate(value):
            _check_type(f"{path}[{i}]", item, get_args(tp)[0])
    elif origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"{path} must be a dict, got {type(value).__name__} {value!r}")
        key_tp, val_tp = get_args(tp)
        for k, v in value.items():
            _check_type(f"{path} key {k!r}", k, key_tp)
            _check_type(f"{path}[{k!r}]", v, val_tp)
    elif origin is types.UnionType:
        if not isinstance(value, get_args(tp)):
            raise TypeError(f"{path} must be {tp}, got {type(value).__name__} {value!r}")
    elif not isinstance(value, tp):
        raise TypeError(f"{path} must be {tp.__name__}, got {type(value).__name__} {value!r}")


def _check_fields(obj: object) -> None:
    for f in fields(obj):
        _check_type(f"{type(obj).__name__}.{f.name}", getattr(obj, f.name), f.type)

#
# The contract is the declarative policy for this script: cleanup rules, footer
# detection, sectioning, and which single-column sums to emit. It lives here as
# a frozen dataclass rather than an external file so it is versioned, shipped,
# and invoked together with the code that reads it. A mistyped field name or a
# wrong-typed value fails at import (TypeError) and an invalid regex fails at
# import (re.error) — no separate schema checker needed. To adapt to a new
# Fidelity layout, edit CONTRACT below; the conversion logic should not need to
# change.

@dataclass(frozen=True)
class Total:
    """One plain single-column sum (CLAUDE.md aggregation carve-out)."""
    label: str
    column: str

    def __post_init__(self) -> None:
        _check_fields(self)


@dataclass(frozen=True)
class DropRow:
    column: str
    regex: str

    def __post_init__(self) -> None:
        _check_fields(self)
        re.compile(self.regex)


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
    # Drop a column whose header repeats an earlier one (ignoring surrounding
    # whitespace and case) when every value matches it — Fidelity's appended
    # summary block. Aborts if any value differs, so nothing is lost silently.
    drop_duplicate_columns: bool

    # ---- sections ----
    # Rows are always grouped by Account Number (a required column), in
    # first-seen order. Each section's H2 heading — and its account-index
    # line — is filled from that account's first row.
    heading_template: str

    # ---- portfolio header (top of file) ----
    summary_header: bool
    # Case-insensitive regex searched across all cells *before* drop_rows; the
    # first capture group is emitted verbatim as "As of:". Missing is non-fatal.
    as_of_pattern: str | None
    # Each sums one column across ALL accounts.
    portfolio_totals: tuple[Total, ...]
    # One "- <heading>: $X" line per account (sum of account_index_column).
    account_index: bool
    account_index_label: str
    account_index_column: str

    # ---- per-account subtotal under each section heading ----
    section_header: bool
    section_totals: tuple[Total, ...]

    def __post_init__(self) -> None:
        # Fail at import, not mid-run: wrong types (incl. the missing-comma
        # tuple typo) and uncompilable patterns. DropRow compiles its own regex.
        _check_fields(self)
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
    drop_rows=(),
    footer_markers=(
        # Matched anywhere in the row, so it works whatever column the
        # footer text lands in. as_of is extracted before this runs.
        "date downloaded",
        "the data and information in this spreadsheet",
        "brokerage services are provided by fidelity brokerage",
        "for informational purposes only",
        "fidelity.com",
    ),
    drop_duplicate_columns=True,
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
    heading: str
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
    dropped_duplicates: list[str]
    position_pairs: Counter
    size: str
    version: str
    dry_run: bool


def _read_csv(csv_path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a CSV into (header, rows): verbatim (possibly duplicate) header
    names, every cell a str exactly as written, every row header-width."""
    # Short rows (Fidelity's footer) are padded to the header width. Surplus
    # fields are dropped only when empty (the trailing-comma export); a
    # non-empty surplus field would be silently lost data, so it aborts.
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        header, *rows = list(csv.reader(f)) or [[]]
    width = len(header)
    for row_no, r in enumerate(rows, start=2):  # CSV records; 1 is the header
        extra = [c for c in r[width:] if c.strip()]
        if extra:
            raise AssertionError(
                f"FAIL CSV row {row_no} has {len(r)} fields but the header has {width}; "
                f"extra non-empty values would be lost: {extra[:5]}"
            )
    return header, [(r + [""] * width)[:width] for r in rows if r]


def _load_and_clean(csv_path: Path, contract: Contract) -> tuple[Table, str | None, Counter, list[str]]:
    """Read, alias, drop duplicate columns, extract as_of, drop rows/columns,
    strip footers, and verify duplicates and required-column integrity.
    Returns (cleaned table, as_of, raw position pairs captured before cleanup
    for loss detection, dropped duplicate column names).
    """
    header, rows = _read_csv(csv_path)

    # Apply column aliases before anything else
    header = [contract.column_aliases.get(h, h) for h in header]

    # Cleanup works on full-width raw rows plus the list of `active` column
    # positions; removed columns (duplicate copies, drop_columns) leave
    # `active` but stay in the rows, so duplicate copies can still be verified
    # after rows are dropped. The output table is projected at the end.
    active = list(range(len(header)))

    def find(name: str) -> int | None:
        return next((i for i in active if header[i] == name), None)

    # Duplicate columns leave `active` now and are verified after cleanup
    # below, on the rows that survive (so footer rows can't cause a spurious
    # mismatch).
    duplicates: list[tuple[int, int]] = []  # (kept position, copy position)
    if contract.drop_duplicate_columns:
        first_seen: dict[str, int] = {}
        for i, name in enumerate(header):
            key = name.strip().casefold()
            if key in first_seen:
                duplicates.append((first_seen[key], i))
            else:
                first_seen[key] = i
        copies = {copy for _, copy in duplicates}
        active = [i for i in active if i not in copies]

    # Header names are kept verbatim, so with dedup off Fidelity's repeated
    # summary block yields duplicate names. Fine for pass-through columns; a
    # repeated required column is ambiguous (which copy is the real one?), so
    # reject it.
    active_names = [header[i] for i in active]
    for col in REQUIRED_COLUMNS:
        if active_names.count(col) > 1:
            raise AssertionError(f"FAIL required column duplicated: '{col}'")

    # Baseline position pairs for loss detection. Only rows with an Account
    # Number can be holdings (an empty one aborts at render anyway); this keeps
    # a one-field footer row out of the baseline when its text lands in Symbol.
    raw_position_pairs: Counter = Counter()
    acct, sym, val = find("Account Number"), find("Symbol"), find("Current value")
    if None not in (acct, sym, val):
        held = [r for r in rows if r[acct].strip()]
        raw_position_pairs = _position_pairs([r[sym] for r in held], [r[val] for r in held])

    # Extract "As of" timestamp BEFORE rows are dropped. The Fidelity
    # "Date downloaded ..." footer is otherwise lost to cleanup. Searched
    # column by column.
    as_of: str | None = None
    if contract.summary_header and contract.as_of_pattern:
        as_of = _extract_as_of((r[i] for i in active for r in rows), contract.as_of_pattern)

    # Drop rows per contract
    for rule in contract.drop_rows:
        i = find(rule.column)
        if i is None:
            print(f"WARNING: drop_rows column '{rule.column}' not in CSV — skipped", file=sys.stderr)
            continue
        pattern = re.compile(rule.regex)
        rows = [r for r in rows if not pattern.match(r[i])]

    # Drop columns per contract (by exact name: every active copy)
    for col in contract.drop_columns:
        if find(col) is None:
            print(f"WARNING: drop_columns entry '{col}' not in CSV — skipped", file=sys.stderr)
        else:
            active = [i for i in active if header[i] != col]

    # Footer/disclaimer removal: case-insensitive substring anywhere in the row
    markers = [m.lower() for m in contract.footer_markers if m.strip()]
    if markers:
        def is_footer(r: list[str]) -> bool:
            text = " | ".join(r[i] for i in active).lower()
            return any(m in text for m in markers)
        rows = [r for r in rows if not is_footer(r)]

    # Verify the removed duplicate copies on the surviving rows
    sym = find("Symbol")
    for kept, copy in duplicates:
        if kept not in active:
            continue  # removed on purpose by drop_columns; nothing to compare
        for n, r in enumerate(rows, start=1):
            a, b = norm_str(r[kept]), norm_str(r[copy])
            if a != b:
                where = f"Symbol {r[sym]!r}" if sym is not None else f"row {n}"
                raise AssertionError(
                    f"FAIL duplicate column {header[copy]!r} differs from {header[kept]!r} "
                    f"at {where}: {a!r} vs {b!r}"
                )

    table = Table([header[i] for i in active], [[r[i] for i in active] for r in rows])

    if contract.summary_header or contract.section_header:
        total_cols = {t.column for t in contract.portfolio_totals + contract.section_totals}
        if contract.account_index:
            total_cols.add(contract.account_index_column)
        _warn_on_total_columns(table, total_cols)

    # ---- Verification ----
    for col in REQUIRED_COLUMNS:
        if col not in table.header:
            raise AssertionError(f"FAIL required column missing: '{col}'")

    if not table.rows:
        raise AssertionError("FAIL no rows after cleanup — check drop rules and footer markers")

    return table, as_of, raw_position_pairs, [header[copy] for _, copy in duplicates]


def _render_section(account: Table, contract: Contract) -> tuple[str, AccountSection]:
    """Validate one account group and render its markdown section. Fail-fast:
    any invalid account aborts the whole file."""
    acct_name_raw = norm_str(account.col("Account Name")[0])
    acct_num_raw = norm_str(account.col("Account Number")[0])

    if not acct_num_raw:
        raise AssertionError("FAIL Account Number is empty for a section")
    if not acct_name_raw:
        raise AssertionError(f"FAIL Account Name is empty for account {acct_num_raw}")

    # Tolerates an empty Symbol when Current value is present (e.g. a 401(k)
    # custom fund) — _position_pairs keeps a pair if either field is non-empty.
    position_pairs = _position_pairs(account.col("Symbol"), account.col("Current value"))
    if not position_pairs:
        raise AssertionError(f"FAIL no valid symbol/value pairs for account {acct_num_raw}")

    heading = _format_heading(contract.heading_template, account.header, account.rows[0])

    totals: list[tuple[str, str]] = []
    if contract.section_header:
        totals = _compute_totals(account, contract.section_totals)

    table = _pipe_table([_md_cell(h) for h in account.header],
                        [[_md_cell(c) for c in r] for r in account.rows])

    lines = [f"## {heading}", ""]
    for label, value in totals:
        lines.append(f"**{label}:** {value}")
    if totals:
        lines.append("")
    lines.append(table)

    section = AccountSection(
        account_name=acct_name_raw,
        account_number=acct_num_raw,
        heading=heading,
        rows=len(account.rows),
        # Holdings, not distinct (symbol, value) pairs: identical lots count.
        positions=sum(position_pairs.values()),
        position_pairs=position_pairs,
        totals=totals,
    )
    return "\n".join(lines), section


def convert_csv(csv_path: Path, out_dir: Path, dry_run: bool, contract: Contract = CONTRACT) -> ConvertResult:
    """
    Convert one CSV to a sectioned markdown file (one section per account).
    Raises on failure. Does not print anything.
    """
    table, as_of, raw_position_pairs, dropped_duplicates = _load_and_clean(csv_path, contract)

    header_enabled = contract.summary_header
    index_enabled = header_enabled and contract.account_index

    # Group by account, preserving first-seen order (dicts keep insertion order).
    groups: dict[str, list[list[str]]] = {}
    for r, acct in zip(table.rows, table.col("Account Number")):
        groups.setdefault(acct, []).append(r)

    sections_md: list[str] = []
    accounts: list[AccountSection] = []
    combined_pairs: Counter = Counter()
    index_lines: list[str] = []

    for group_rows in groups.values():
        group = Table(table.header, group_rows)
        section_md, section = _render_section(group, contract)
        sections_md.append(section_md)
        accounts.append(section)
        combined_pairs.update(section.position_pairs)

        if index_enabled:
            total_str = _sum_column(group, contract.account_index_column)
            suffix = f": {total_str}" if total_str else ""
            index_lines.append(f"- {section.heading}{suffix}")

    # ---- Global positions-loss check (across all accounts) ----
    if raw_position_pairs:
        lost = raw_position_pairs - combined_pairs
        if lost:
            raise AssertionError(f"FAIL positions lost during cleanup: {dict(lost)}")

    # ---- Portfolio header (always emitted when enabled) ----
    portfolio_totals: list[tuple[str, str]] = []
    header_lines: list[str] = []
    if header_enabled:
        portfolio_totals = _compute_totals(table, contract.portfolio_totals)
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
        rows=len(table.rows),
        cols=len(table.header),
        dropped_duplicates=dropped_duplicates,
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
    if r.dropped_duplicates:
        print(f"deduped   {len(r.dropped_duplicates)} identical duplicate columns: "
              + ", ".join(repr(c) for c in r.dropped_duplicates))
    print()
    for section in r.accounts:
        print(f"## {section.heading}  rows={section.rows} pos={section.positions}")
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

    total = len(csv_files)
    batch = total > 1
    show_bar = batch and not args.quiet and not args.verbose
    errors = []

    for i, csv_path in enumerate(csv_files, 1):
        out_dir = Path(args.outdir).expanduser().resolve() if args.outdir else csv_path.parent
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)

        if show_bar:
            sys.stdout.write(f"\r{_bar(i, total)}  {csv_path.name:<40}")
            sys.stdout.flush()

        try:
            result = convert_csv(csv_path, out_dir, args.dry_run)

            if args.verbose:
                if batch:
                    print(f"\n[{i}/{total}] {csv_path.name}")
                print_result_verbose(result)
            elif not args.quiet:
                if batch:
                    sys.stdout.write("\n")
                print_result_quiet(result)

        except Exception as exc:
            if show_bar:
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
