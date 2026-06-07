# fidelity-to-markdown

Converts Fidelity "Positions" CSV exports into LLM-ready markdown for portfolio analysis.

The intended workflow: export your account positions from Fidelity → run the script → provide the markdown output to Claude, ChatGPT, or another LLM for analysis (allocation review, tax lot examination, drift detection, etc.). The script preserves all values as strings — no numeric coercion — so the LLM sees exactly what Fidelity shows.

---

## Scripts

### `fidelity_csv_to_markdown.py`

Converts Fidelity "Positions" CSV exports into markdown format. Supports single-file and batch (directory) mode. Each input CSV produces one output file named after the input stem (e.g. `Portfolio_Positions_Jun-06-2026.md`).

> **Multi-account aware.** The CSV is grouped by `Account Number` and rendered as one file with a `## {Account Name} ({Account Number})` section per account. Feed an "All Accounts" Fidelity export directly — a single-account export is simply the one-section case. (Sections, not a flat table, because `% of account` is per-account in the source.)
>
> **No silent overwrites.** If the stem-named output file already exists in the output directory, the script aborts rather than overwriting it. Remove or move the existing file to rerun.
>
> **Portfolio header above the sections.** Each file opens with an `**As of:**` line (extracted from the Fidelity `Date downloaded` footer), a portfolio `**Total Current Value:**` line (sum of the `Current value` column across all accounts — not a Fidelity-quoted balance), and an account index listing each account with its subtotal. Each section then carries its own subtotal. All totals are plain single-column sums (no ratios or percentages-of-portfolio). Configured under `output.markdown.summary_header` / `section_header` / `sections` in the YAML contract; set `enabled: false` on a header block to suppress it.

---

## Setup

```bash
./setup_env.sh
```

Creates a `.venv` virtual environment and installs dependencies from `requirements.txt`.

To activate in subsequent sessions:

```bash
source activate_env.sh
```

---

## Usage

### CSV → Markdown

```
usage: fidelity_csv_to_markdown.py (--csv FILE | --csvdir DIR) --contract FILE [--outdir DIR] [--dry-run] [--verbose] [--quiet]
```

Single file:
```bash
python fidelity_csv_to_markdown.py \
  --csv path/to/positions.csv \
  --contract fidelity_csv_to_markdown.yaml
```

Batch (all CSVs in a directory):
```bash
python fidelity_csv_to_markdown.py \
  --csvdir path/to/exports/ \
  --contract fidelity_csv_to_markdown.yaml
```

**Arguments:**

| Argument | Required | Description |
| --- | --- | --- |
| `--csv` | Yes (or `--csvdir`) | Single Fidelity positions CSV |
| `--csvdir` | Yes (or `--csv`) | Directory of CSVs to process |
| `--contract` | Yes | Path to the YAML contract file |
| `--outdir` | No | Output directory (default: alongside each input file) |
| `--dry-run` | No | Validate without writing output |
| `--verbose` | No | Detailed block output per file instead of one-line summary |
| `--quiet` | No | Suppress all output except errors |

---

## Fidelity Portal Column Selection

The script is contract-driven — optional columns can be added, removed, or renamed via the contract without code changes — but the column set below is optimized for LLM portfolio analysis. Four columns are required and the run will abort if any are missing: `Account Name`, `Account Number`, `Symbol`, `Current value`. Configure **My View** in the Fidelity positions page before exporting to include these columns. An LLM given this data can reason about allocation, cost basis, embedded gains, income, fund costs, and sector exposure in a single pass.

**Account & position identity**
- Account Number
- Account Name
- Symbol
- Description
- Security type
- Security subtype
- Account type

**Sizing & cost**
- Current value
- % of account
- Quantity
- Average cost basis
- Cost basis total

**Performance**
- Today's gain/loss $
- Today's gain/loss %
- Total gain/loss $
- Total gain/loss %
- YTD
- 1 year
- 3 year
- 5 year
- 10 year

**Pricing**
- Last price
- Currency
- Change $
- Change %

**Income & distributions**
- Ex-date
- Amount per share
- Pay date
- Payment frequency
- Dist. yield
- Distribution yield as of
- SEC yield
- SEC yield as of
- Est. annual income

**Fund metadata**
- Exp ratio (net)
- Exp ratio (gross)
- Morningstar category

**Equity classification**
- Sector
- Industry
- Industry group
- Sub industry

> Fidelity appends a duplicate summary block at the end of each row repeating cost basis, gain/loss, last price, and change (`Change $` appears twice). These duplicate columns are preserved as-is alongside the primary columns.

---

## Contract Files

Each script is paired with a YAML contract file that externalizes cleanup rules, footer/disclaimer detection markers, output policy, and validation constraints. Contracts are not shared between scripts.

| Contract | Used by |
| --- | --- |
| `fidelity_csv_to_markdown.yaml` | `fidelity_csv_to_markdown.py` |

Key contract knobs under `input_cleanup`:

- `column_aliases` — rename incoming columns before processing (e.g. handle Fidelity layout changes without renaming downstream).
- `drop_columns` — remove columns from the output entirely.
- `drop_rows` — regex-match rows to drop (e.g. `Date downloaded` summary rows).
- `footer_detection_policy.prefer_disclaimer_markers` — case-insensitive substrings that mark disclaimer/footer rows for removal.

And under `output.markdown`:

- `sections.group_by` — column the file is split on (default `Account Number`); `sections.heading_template` — each section's H2 heading, built from that account's first row (e.g. `{Account Name} ({Account Number})`). Account order is first-seen (no sorting).
- `summary_header` — the **portfolio** header at the top of the file. `.enabled` toggles it; `.as_of.pattern` is a case-insensitive regex searched across every cell *before* `drop_rows` runs (first capture group emitted verbatim); `.totals` is a list of `{label, column}` entries each summing the named column across **all** accounts; `.account_index` (`enabled`, `label`, `total_column`) lists each account with its own subtotal.
- `section_header` — the **per-account** subtotal printed under each section heading. Same `{label, column}` totals, scoped to that account.

Unparseable cells (`--`, blank) are skipped in any sum; a missing column logs a warning and skips that line. All totals are plain pass-through aggregations; see CLAUDE.md "Carve-out for plain aggregation" for the policy boundary.

To adapt the pipeline to a different CSV layout or add cleanup rules, update the contract — the script logic should not need to change.

The contract is schema-checked when it loads: unknown keys, wrong types, and uncompilable regexes in the behavior-bearing blocks abort the run with a list of problems, so a typo (e.g. `heading-template` for `heading_template`) fails loudly instead of silently falling back to a default.

---

## Tests

Pytest suite under `tests/` covers `convert_csv()` and CLI behavior.

```bash
pip install -r requirements-dev.txt
pytest
```

---

## Privacy Note

Fidelity exports contain account numbers and position details. Do not commit CSV exports or generated markdown to version control. Both `*.csv` and `*.md` output files are gitignored by default (README.md and CLAUDE.md are excluded from that rule).
