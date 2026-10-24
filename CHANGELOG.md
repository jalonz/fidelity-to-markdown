# Changelog

History for `fidelity_csv_to_markdown.py`. Until 4.0.0 the YAML contract
carried its own version line (contract 1.0.0 → 3.0.0); since 4.0.0 the contract
is inline and shares the script's version.

## 4.0.0 — 2026-10-24

- **Breaking:** the contract is now inline: the `CONTRACT` constant, a frozen
  `Contract` dataclass in the script. The `--contract` flag and
  `fidelity_csv_to_markdown.yaml` are removed. A mistyped field raises
  `TypeError` and an invalid regex raises `re.error` at import, replacing the
  hand-rolled `validate_contract` schema checker. PyYAML is no longer a
  dependency.
- `convert_csv(csv_path, out_dir, dry_run, contract=CONTRACT)`: the contract is
  an optional keyword (a test seam), not a positional argument.
- Fix: numeric-looking strings are preserved verbatim in tables. tabulate's
  numparse had rewritten values such as `1.50` → `1.5` and `0.000` → `0`.
- CSV read goes through a single `csv.reader` path (rows padded or truncated
  to the header width); pandas no longer parses the file, so there is no
  NaN handling.
- Removed the "columns unexpectedly dropped" check, which could never fail.
- One `_sum_column` helper backs the portfolio totals, the section subtotals,
  and the account index.
- Changelog moved from the module docstring to this file.
- PEP 723 inline script metadata: `uv run fidelity_csv_to_markdown.py ...` works
  with no manual venv.

## 3.0.0 — 2026-06-06

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

## 2.3.0 — 2026-05-21

- Emit a contract-driven summary header above the markdown table: an
  "**As of:** <timestamp>" line extracted from the Fidelity "Date downloaded"
  footer, plus one "**<label>:** $X,XXX.XX" line per configured total
  (default: Total Current Value). Driven by output.markdown.summary_header
  in the YAML contract; set enabled: false to suppress. Summing one column
  verbatim is treated as formatting under CLAUDE.md's aggregation carve-out.
- ConvertResult gains as_of and totals fields; --verbose prints both.

## 2.2.0 — 2026-05-20

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

## 2.1.0 — 2026-04-18

- Output modes redesigned: default is brief one-line summary; --verbose for
  full detail block; --quiet suppresses all stdout (errors only on stderr).
- Animated progress bar in default batch mode (was --quiet).

## 2.0.0 — 2026-04-18

- Add --csvdir for batch mode: process all CSVs in a directory.
- Add --dry-run: validate and report without writing files.
- Add --quiet: one-line summary per file; animated progress bar in batch.
- Progress display in batch mode: [n/total] prefix in verbose mode.
- Cleaner verification output with named check results.
- Verification failures now report the specific check that failed.
- Contract: support drop_columns list in input_cleanup.
- Contract: support column_aliases map in input_cleanup.

## 1.1.0 — 2026-03-26

- Guard against df.to_markdown() returning None; raise AssertionError on empty output.
- Save pre-cleanup position pairs and diff against post-cleanup to catch positions
  silently dropped by footer or drop_rows rules.
- Warn to stderr when a contract drop rule references a column absent from the CSV.

## 1.0.0 — 2026-03-26

- Derived from fidelity_csv_to_parquet v1.1.3.
- Replaced Parquet output with a single markdown table.
- Removed lossless/optimized layer concept; all original columns preserved as-is.
- Removed companion column derivation (__usd, __pct) and pyarrow dependency.
- Verification moved to pre-write in-memory checks against the cleaned DataFrame.
