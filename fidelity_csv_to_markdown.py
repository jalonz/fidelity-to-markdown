#!/usr/bin/env python3
"""
fidelity_csv_to_markdown

Version: 2.1.0
Date: 2026-04-18

Changelog:
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
Converts Fidelity positions CSV exports into markdown tables using a YAML
contract for cleanup, validation, and output policy. All original columns
and string values are preserved without modification (unless drop_columns
is specified in the contract).
"""

import argparse
from collections import Counter
import re
import sys
from pathlib import Path

import pandas as pd
import yaml


# ================================
# Helpers
# ================================

def normalize_account_name(value: str) -> str:
    cleaned = value.lower().encode("ascii", "ignore").decode()
    cleaned = re.sub(r"[^a-z0-9_-]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:100]


def normalize_account_number(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", value.lower())


def norm_str(val: object) -> str:
    return "" if pd.isna(val) else str(val).strip()


def _bar(current: int, total: int, width: int = 28) -> str:
    filled = round(width * current / total) if total else width
    bar = "=" * (filled - 1) + (">" if filled < width else "=") + " " * (width - filled)
    return f"[{bar}] {current}/{total}"


def _size_str(path: Path) -> str:
    size = path.stat().st_size
    return f"{size / 1024:.1f}KB" if size >= 1024 else f"{size}B"


# ================================
# Core conversion
# ================================

def convert_csv(csv_path: Path, contract: dict, out_dir: Path, dry_run: bool) -> dict:
    """
    Convert one CSV to markdown. Returns a result dict; raises on failure.
    Does not print anything.
    """
    contract_meta = contract.get("contract", {})
    contract_version = contract_meta.get("version", "unknown")
    contract_name = contract_meta.get("name", "unknown")
    cleanup = contract.get("input_cleanup", {})

    df = pd.read_csv(csv_path, dtype=str, index_col=False, encoding="utf-8-sig")
    original_columns = list(df.columns)

    # Apply column aliases before anything else
    aliases = cleanup.get("column_aliases", {}) or {}
    if aliases:
        df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})

    aliased_columns = [aliases.get(c, c) for c in original_columns]

    # Baseline position pairs for loss detection
    raw_position_pairs: Counter = Counter()
    if "Symbol" in df.columns and "Current value" in df.columns:
        raw_position_pairs = Counter(
            (norm_str(sym), norm_str(val))
            for sym, val in zip(df["Symbol"], df["Current value"])
            if norm_str(sym) or norm_str(val)
        )

    # Drop rows per contract
    for rule in cleanup.get("drop_rows", []):
        col, regex = rule.get("column"), rule.get("regex")
        if col not in df.columns:
            print(f"WARNING: drop_rows column '{col}' not in CSV — skipped", file=sys.stderr)
            continue
        if regex:
            df = df[~df[col].astype(str).str.match(regex, na=False)]

    # Drop columns per contract
    drop_cols = cleanup.get("drop_columns", []) or []
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
        else:
            print(f"WARNING: drop_columns entry '{col}' not in CSV — skipped", file=sys.stderr)

    # Footer/disclaimer removal
    markers = cleanup.get("footer_detection_policy", {}).get("prefer_disclaimer_markers", [])
    if markers:
        markers_lc = [m.lower() for m in markers if isinstance(m, str) and m.strip()]
        if markers_lc:
            row_text = df.fillna("").astype(str).agg(" | ".join, axis=1).str.lower()
            pattern = "|".join(re.escape(m) for m in markers_lc)
            df = df[~row_text.str.contains(pattern, regex=True, na=False)]

    # ---- Verification ----
    expected_cols = [c for c in aliased_columns if c not in drop_cols]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        raise AssertionError(f"FAIL columns unexpectedly dropped: {missing}")

    for col in ("Account Name", "Account Number"):
        if col not in df.columns:
            raise KeyError(f"FAIL required column missing: '{col}'")

    if len(df) == 0:
        raise AssertionError("FAIL no rows after cleanup — check drop rules and footer markers")

    acct_name_raw = norm_str(df["Account Name"].iloc[0])
    acct_num_raw = norm_str(df["Account Number"].iloc[0])

    if not acct_name_raw:
        raise AssertionError("FAIL Account Name is empty after cleanup")
    if not acct_num_raw:
        raise AssertionError("FAIL Account Number is empty after cleanup")

    for col in ("Symbol", "Current value"):
        if col not in df.columns:
            raise KeyError(f"FAIL required column missing: '{col}'")

    position_pairs = Counter(
        (norm_str(sym), norm_str(val))
        for sym, val in zip(df["Symbol"], df["Current value"])
        if norm_str(sym) or norm_str(val)
    )
    if not position_pairs:
        raise AssertionError("FAIL no valid symbol/value pairs after cleanup")

    if raw_position_pairs:
        lost = raw_position_pairs - position_pairs
        if lost:
            raise AssertionError(f"FAIL positions lost during cleanup: {dict(lost)}")

    # ---- Output ----
    acct_name = normalize_account_name(acct_name_raw)
    acct_num = normalize_account_number(acct_num_raw)
    out_path = out_dir / f"{acct_name}__{acct_num}.md"

    markdown = df.to_markdown(index=False)
    if not markdown:
        raise AssertionError("FAIL markdown serialization produced no output")

    if not dry_run:
        out_path.write_text(markdown, encoding="utf-8")
        size = _size_str(out_path)
    else:
        size = "dry-run"

    return {
        "out_path": out_path,
        "account_name": acct_name_raw,
        "account_number": acct_num_raw,
        "rows": len(df),
        "cols": len(df.columns),
        "positions": len(position_pairs),
        "size": size,
        "contract_name": contract_name,
        "contract_version": contract_version,
        "position_pairs": position_pairs,
        "dry_run": dry_run,
    }


# ================================
# Output formatting
# ================================

def print_result_verbose(r: dict, prefix: str = "") -> None:
    header = f"{prefix}=== {r['out_path'].name} ==="
    print(header)
    print(f"account   {r['account_name']} ({r['account_number']})")
    print(f"rows      {r['rows']}  cols  {r['cols']}  size  {r['size']}")
    print(f"contract  {r['contract_name']} v{r['contract_version']}")
    tag = " [dry-run]" if r["dry_run"] else ""
    print(f"checks    ✓ columns intact  ✓ {r['positions']} positions  ✓ no losses{tag}")
    print()
    for (sym, val), count in sorted(r["position_pairs"].items()):
        suffix = f" (x{count})" if count > 1 else ""
        print(f"  {sym:<12} {val}{suffix}")


def print_result_quiet(r: dict, prefix: str = "") -> None:
    tag = " [dry-run]" if r["dry_run"] else ""
    print(
        f"✓ {prefix}{r['out_path'].name}"
        f"  {r['account_name']} ({r['account_number']})"
        f"  rows={r['rows']} pos={r['positions']} size={r['size']}{tag}"
    )


# ================================
# Main
# ================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert Fidelity positions CSV(s) to Markdown"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Single input Fidelity positions CSV")
    source.add_argument("--csvdir", help="Directory of CSVs to process in batch")
    parser.add_argument("--contract", required=True, help="YAML contract path")
    parser.add_argument("--outdir", help="Output directory (default: alongside each input file)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing output")
    parser.add_argument("--verbose", action="store_true", help="Detailed block output per file")
    parser.add_argument("--quiet", action="store_true", help="Suppress all output except errors")

    args = parser.parse_args()

    contract_path = Path(args.contract).expanduser().resolve()
    if not contract_path.exists():
        print(f"ERROR: contract not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = yaml.safe_load(f) or {}

    if not contract.get("contract", {}).get("version"):
        print("ERROR: contract.version missing in YAML", file=sys.stderr)
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
        csv_files = sorted(d.glob("*.csv"))
        if not csv_files:
            print(f"ERROR: no CSV files found in {d}", file=sys.stderr)
            sys.exit(1)

    def out_dir_for(csv_path: Path) -> Path:
        if args.outdir:
            return Path(args.outdir).expanduser().resolve()
        return csv_path.parent if args.csvdir else Path(".")

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
