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
from collections import Counter
from dataclasses import dataclass
import re
import sys
from pathlib import Path

import pandas as pd
import yaml


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
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None
    for col in df.columns:
        series = df[col].dropna().astype(str)
        for val in series:
            m = compiled.search(val)
            if m:
                return (m.group(1) if m.groups() else m.group(0)).strip()
    return None


def _compute_totals(df: pd.DataFrame, totals_cfg: list | None) -> list[tuple[str, str]]:
    """Sum each configured column verbatim and format as USD.

    Plain pass-through aggregation (CLAUDE.md carve-out) — one column summed,
    no ratios or derived values. Unparseable cells ('--', blank) are skipped; a
    missing column logs a warning and yields no line.
    """
    totals: list[tuple[str, str]] = []
    for entry in totals_cfg or []:
        label = entry.get("label")
        col = entry.get("column")
        if not label or not col:
            continue
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


def _markdown_cfg(contract: dict) -> dict:
    return contract.get("output", {}).get("markdown", {}) or {}


def _portfolio_header_cfg(contract: dict) -> dict:
    return _markdown_cfg(contract).get("summary_header", {}) or {}


def _section_header_cfg(contract: dict) -> dict:
    return _markdown_cfg(contract).get("section_header", {}) or {}


def _sections_cfg(contract: dict) -> dict:
    return _markdown_cfg(contract).get("sections", {}) or {}


# ================================
# Contract validation
# ================================
#
# The contract is load-bearing: cleanup, footer detection, and output policy all
# live in it, and the conversion code reads keys with silent defaults. A typo'd
# key (heading-template for heading_template) or a wrong type would therefore
# degrade quietly to default behavior. validate_contract closes that gap at the
# load boundary — it rejects unknown keys, wrong types, and uncompilable regexes
# in the behavior-bearing subtrees, returning a list of problems (empty == valid)
# so main() can abort loudly. Descriptive metadata (changelog, task, input,
# constraints) is intentionally not policed: an unknown key there is harmless.

def _reject_unknown(path: str, node: dict, allowed: set, errors: list) -> None:
    for key in node:
        if key not in allowed:
            errors.append(f"{path}: unknown key '{key}'")


def _require_type(path: str, value: object, types, type_name: str, errors: list) -> bool:
    # bool is a subclass of int; guard against it leaking past an int check.
    if types is int and isinstance(value, bool):
        errors.append(f"{path}: must be {type_name}")
        return False
    if not isinstance(value, types):
        errors.append(f"{path}: must be {type_name}")
        return False
    return True


def _validate_regex(path: str, value: object, errors: list) -> None:
    if not _require_type(path, value, str, "a string", errors):
        return
    try:
        re.compile(value)
    except re.error as exc:
        errors.append(f"{path}: invalid regex ({exc})")


def _validate_totals(path: str, totals: object, errors: list) -> None:
    if not _require_type(path, totals, list, "a list", errors):
        return
    for i, entry in enumerate(totals):
        p = f"{path}[{i}]"
        if not _require_type(p, entry, dict, "a mapping", errors):
            continue
        _reject_unknown(p, entry, {"label", "column"}, errors)
        for key in ("label", "column"):
            if key not in entry:
                errors.append(f"{p}.{key}: required")
            else:
                _require_type(f"{p}.{key}", entry[key], str, "a string", errors)


def _validate_sections(sections: object, errors: list) -> None:
    if sections is None:
        return
    p = "output.markdown.sections"
    if not _require_type(p, sections, dict, "a mapping", errors):
        return
    _reject_unknown(p, sections, {"group_by", "heading_template"}, errors)
    for key in ("group_by", "heading_template"):
        if key in sections:
            _require_type(f"{p}.{key}", sections[key], str, "a string", errors)


def _validate_summary_header(sh: object, errors: list) -> None:
    if sh is None:
        return
    p = "output.markdown.summary_header"
    if not _require_type(p, sh, dict, "a mapping", errors):
        return
    _reject_unknown(p, sh, {"enabled", "as_of", "totals", "account_index"}, errors)
    if "enabled" in sh:
        _require_type(f"{p}.enabled", sh["enabled"], bool, "a boolean", errors)
    if "as_of" in sh:
        ao = sh["as_of"]
        if _require_type(f"{p}.as_of", ao, dict, "a mapping", errors):
            _reject_unknown(f"{p}.as_of", ao, {"pattern"}, errors)
            if "pattern" in ao:
                _validate_regex(f"{p}.as_of.pattern", ao["pattern"], errors)
    if "totals" in sh:
        _validate_totals(f"{p}.totals", sh["totals"], errors)
    if "account_index" in sh:
        ai = sh["account_index"]
        if _require_type(f"{p}.account_index", ai, dict, "a mapping", errors):
            _reject_unknown(f"{p}.account_index", ai, {"enabled", "label", "total_column"}, errors)
            if "enabled" in ai:
                _require_type(f"{p}.account_index.enabled", ai["enabled"], bool, "a boolean", errors)
            for key in ("label", "total_column"):
                if key in ai:
                    _require_type(f"{p}.account_index.{key}", ai[key], str, "a string", errors)


def _validate_section_header(sh: object, errors: list) -> None:
    if sh is None:
        return
    p = "output.markdown.section_header"
    if not _require_type(p, sh, dict, "a mapping", errors):
        return
    _reject_unknown(p, sh, {"enabled", "totals"}, errors)
    if "enabled" in sh:
        _require_type(f"{p}.enabled", sh["enabled"], bool, "a boolean", errors)
    if "totals" in sh:
        _validate_totals(f"{p}.totals", sh["totals"], errors)


def _validate_input_cleanup(cleanup: object, errors: list) -> None:
    if not _require_type("input_cleanup", cleanup, dict, "a mapping", errors):
        return
    _reject_unknown("input_cleanup", cleanup,
                    {"column_aliases", "drop_columns", "drop_rows", "footer_detection_policy"}, errors)

    if "column_aliases" in cleanup:
        _require_type("input_cleanup.column_aliases", cleanup["column_aliases"], dict, "a mapping", errors)

    if "drop_columns" in cleanup:
        dc = cleanup["drop_columns"]
        if _require_type("input_cleanup.drop_columns", dc, list, "a list", errors):
            for i, col in enumerate(dc):
                _require_type(f"input_cleanup.drop_columns[{i}]", col, str, "a string", errors)

    if "drop_rows" in cleanup:
        dr = cleanup["drop_rows"]
        if _require_type("input_cleanup.drop_rows", dr, list, "a list", errors):
            for i, rule in enumerate(dr):
                p = f"input_cleanup.drop_rows[{i}]"
                if not _require_type(p, rule, dict, "a mapping", errors):
                    continue
                _reject_unknown(p, rule, {"column", "regex"}, errors)
                if "column" not in rule:
                    errors.append(f"{p}.column: required")
                else:
                    _require_type(f"{p}.column", rule["column"], str, "a string", errors)
                if "regex" in rule:
                    _validate_regex(f"{p}.regex", rule["regex"], errors)

    if "footer_detection_policy" in cleanup:
        fdp = cleanup["footer_detection_policy"]
        if _require_type("input_cleanup.footer_detection_policy", fdp, dict, "a mapping", errors):
            _reject_unknown("input_cleanup.footer_detection_policy", fdp,
                            {"prefer_disclaimer_markers", "do_not_use_as_markers", "intent", "notes"}, errors)
            for key in ("prefer_disclaimer_markers", "do_not_use_as_markers", "notes"):
                if key in fdp:
                    _require_type(f"input_cleanup.footer_detection_policy.{key}", fdp[key], list, "a list", errors)


def validate_contract(contract: dict) -> list:
    """Return a list of human-readable problems with the contract (empty == valid).

    Checks the behavior-bearing subtrees only — a malformed contract aborts the
    run rather than silently degrading to default behavior. See section comment.
    """
    errors: list = []
    if not isinstance(contract, dict):
        return ["contract: top level must be a mapping"]

    _reject_unknown("(top level)", contract,
                    {"contract", "changelog", "task", "input", "validation", "output", "constraints", "input_cleanup"},
                    errors)

    meta = contract.get("contract")
    if not isinstance(meta, dict):
        errors.append("contract: required mapping is missing")
    elif not meta.get("version"):
        errors.append("contract.version: required")

    if "input_cleanup" in contract:
        _validate_input_cleanup(contract["input_cleanup"], errors)

    if "output" in contract:
        output = contract["output"]
        if _require_type("output", output, dict, "a mapping", errors):
            _reject_unknown("output", output, {"markdown"}, errors)
            if "markdown" in output:
                md = output["markdown"]
                if _require_type("output.markdown", md, dict, "a mapping", errors):
                    _reject_unknown("output.markdown", md,
                                    {"include_all_columns", "preserve_column_order", "preserve_string_values",
                                     "purpose", "sections", "summary_header", "section_header", "filename_policy"},
                                    errors)
                    _validate_sections(md.get("sections"), errors)
                    _validate_summary_header(md.get("summary_header"), errors)
                    _validate_section_header(md.get("section_header"), errors)
                    if "filename_policy" in md:
                        # Descriptive only — the output filename is code-driven.
                        _require_type("output.markdown.filename_policy", md["filename_policy"], dict, "a mapping", errors)

    return errors


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
    contract_name: str
    contract_version: str
    dry_run: bool


def _load_and_clean(csv_path: Path, contract: dict) -> tuple[pd.DataFrame, str | None, Counter]:
    """Read, alias, extract as_of, drop rows/columns, strip footers, and verify
    column/required-column integrity. Returns (cleaned df, as_of, raw position
    pairs captured before cleanup for loss detection).
    """
    cleanup = contract.get("input_cleanup", {})

    # keep_default_na=False: empty cells stay empty strings rather than float
    # NaN. Without it, blank source cells render as the literal "nan" in the
    # markdown — a string-preservation violation that injects a phantom value
    # (see CLAUDE.md "String preservation is intentional"). Fidelity uses "--"
    # for N/A (already a literal string) and blank for empty; nothing in the
    # data relies on NaN coercion.
    df = pd.read_csv(csv_path, dtype=str, index_col=False, encoding="utf-8-sig",
                     keep_default_na=False)

    # Apply column aliases before anything else
    aliases = cleanup.get("column_aliases") or {}
    if aliases:
        df = df.rename(columns=aliases)

    aliased_columns = list(df.columns)

    # Baseline position pairs for loss detection
    raw_position_pairs: Counter = Counter()
    if "Symbol" in df.columns and "Current value" in df.columns:
        raw_position_pairs = _position_pairs(df["Symbol"], df["Current value"])

    # Extract "As of" timestamp BEFORE drop_rows strips it. The Fidelity
    # "Date downloaded ..." footer is otherwise lost to cleanup.
    header_cfg = _portfolio_header_cfg(contract)
    as_of: str | None = None
    if header_cfg.get("enabled", False):
        as_of_pattern = (header_cfg.get("as_of") or {}).get("pattern")
        if as_of_pattern:
            as_of = _extract_as_of(df, as_of_pattern)

    # Drop rows per contract
    for rule in cleanup.get("drop_rows", []):
        col, regex = rule.get("column"), rule.get("regex")
        if col not in df.columns:
            print(f"WARNING: drop_rows column '{col}' not in CSV — skipped", file=sys.stderr)
            continue
        if regex:
            df = df[~df[col].str.match(regex, na=False)]

    # Drop columns per contract
    drop_cols = cleanup.get("drop_columns") or []
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
        else:
            print(f"WARNING: drop_columns entry '{col}' not in CSV — skipped", file=sys.stderr)

    # Footer/disclaimer removal (skip on empty df: agg+axis=1 on zero rows
    # returns a DataFrame instead of a Series in pandas 3.x and crashes the
    # .str accessor)
    markers = cleanup.get("footer_detection_policy", {}).get("prefer_disclaimer_markers", [])
    if markers and not df.empty:
        markers_lc = [m.lower() for m in markers if isinstance(m, str) and m.strip()]
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


def _render_section(df_account: pd.DataFrame, contract: dict) -> tuple[str, AccountSection]:
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

    heading_template = _sections_cfg(contract).get("heading_template") or "{Account Name} ({Account Number})"
    heading = _format_heading(heading_template, df_account.iloc[0])

    section_cfg = _section_header_cfg(contract)
    totals: list[tuple[str, str]] = []
    if section_cfg.get("enabled", False):
        totals = _compute_totals(df_account, section_cfg.get("totals"))

    table = df_account.to_markdown(index=False)
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


def convert_csv(csv_path: Path, contract: dict, out_dir: Path, dry_run: bool) -> ConvertResult:
    """
    Convert one CSV to a sectioned markdown file (one section per account).
    Raises on failure. Does not print anything.
    """
    contract_meta = contract.get("contract", {})
    contract_version = contract_meta.get("version", "unknown")
    contract_name = contract_meta.get("name", "unknown")

    df, as_of, raw_position_pairs = _load_and_clean(csv_path, contract)

    header_cfg = _portfolio_header_cfg(contract)
    header_enabled = bool(header_cfg.get("enabled", False))
    index_cfg = header_cfg.get("account_index") or {}
    index_enabled = header_enabled and bool(index_cfg.get("enabled", False))
    index_total_col = index_cfg.get("total_column")

    group_by = _sections_cfg(contract).get("group_by") or "Account Number"

    # Group by account, preserving first-seen order (sort=False).
    sections_md: list[str] = []
    accounts: list[AccountSection] = []
    combined_pairs: Counter = Counter()
    index_lines: list[str] = []

    for _, group in df.groupby(group_by, sort=False):
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
        portfolio_totals = _compute_totals(df, header_cfg.get("totals"))
        if as_of:
            header_lines.append(f"**As of:** {as_of}")
        for label, value in portfolio_totals:
            header_lines.append(f"**{label}:** {value}")
        if index_enabled and index_lines:
            if header_lines:
                header_lines.append("")
            header_lines.append(f"**{index_cfg.get('label', 'Accounts')}:**")
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
        contract_name=contract_name,
        contract_version=contract_version,
        dry_run=dry_run,
    )


# ================================
# Output formatting
# ================================

def print_result_verbose(r: ConvertResult) -> None:
    print(f"=== {r.out_path.name} ===")
    print(f"accounts  {len(r.accounts)}  rows  {r.rows}  cols  {r.cols}  size  {r.size}")
    print(f"contract  {r.contract_name} v{r.contract_version}")
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
        sys.stderr.write(f"  {prog} --csv FILE --contract YAML [options]\n")
        sys.stderr.write(f"  {prog} --csvdir DIR --contract YAML [options]\n\n")
        sys.stderr.write(f"Run '{prog} --help' for the full option list.\n")
        sys.exit(2)


def main():
    parser = _FormattedArgumentParser(
        description="Convert Fidelity positions CSV(s) to Markdown"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Single input Fidelity positions CSV")
    source.add_argument("--csvdir", help="Directory of CSVs to process in batch")
    parser.add_argument("--contract", required=True, help="YAML contract path")
    parser.add_argument("--outdir", help="Output directory (default: alongside each input file)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument("--verbose", action="store_true", help="Detailed block output per file")
    output_mode.add_argument("--quiet", action="store_true", help="Suppress all output except errors")

    args = parser.parse_args()

    contract_path = Path(args.contract).expanduser().resolve()
    if not contract_path.exists():
        print(f"ERROR: contract not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = yaml.safe_load(f) or {}

    schema_errors = validate_contract(contract)
    if schema_errors:
        print(f"ERROR: malformed contract {contract_path}:", file=sys.stderr)
        for problem in schema_errors:
            print(f"  - {problem}", file=sys.stderr)
        sys.exit(1)

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
            result = convert_csv(csv_path, contract, out_dir, args.dry_run)

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
