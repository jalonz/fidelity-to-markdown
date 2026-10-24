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
> **Portfolio header above the sections.** Each file opens with an `**As of:**` line (extracted from the Fidelity `Date downloaded` footer), a portfolio `**Total Current Value:**` line (sum of the `Current value` column across all accounts — not a Fidelity-quoted balance), and an account index listing each account with its subtotal. Each section then carries its own subtotal. All totals are plain single-column sums (no ratios or percentages-of-portfolio). Configured by the `summary_header` / `section_header` / `account_index` fields of the inline `CONTRACT`; set one to `False` to suppress that block.

---

## Setup

None. The script uses only the Python standard library and needs Python 3.10 or later — no packages, no venv:

```bash
python3 fidelity_csv_to_markdown.py --csv path/to/positions.csv
# or run it directly (python3 shebang):
./fidelity_csv_to_markdown.py --csv path/to/positions.csv
```

[uv](https://docs.astral.sh/uv/) users can also `uv run fidelity_csv_to_markdown.py ...`; the inline [PEP 723](https://peps.python.org/pep-0723/) block declares the Python version and no dependencies.

---

## Usage

```
usage: fidelity_csv_to_markdown.py (--csv FILE | --csvdir DIR) [--outdir DIR] [--dry-run] [--verbose | --quiet]
```

Single file:
```bash
python3 fidelity_csv_to_markdown.py --csv path/to/positions.csv
```

Batch (all CSVs in a directory):
```bash
python3 fidelity_csv_to_markdown.py --csvdir path/to/exports/
```

**Arguments:**

| Argument | Required | Description |
| --- | --- | --- |
| `--csv` | Yes (or `--csvdir`) | Single Fidelity positions CSV |
| `--csvdir` | Yes (or `--csv`) | Directory of CSVs to process |
| `--outdir` | No | Output directory (default: alongside each input file) |
| `--dry-run` | No | Validate without writing output |
| `--verbose` | No | Detailed block output per file instead of one-line summary |
| `--quiet` | No | Suppress all output except errors |

---

## Fidelity Portal Column Selection

The script is contract-driven — optional columns can be added, removed, or renamed by editing `CONTRACT` without touching the conversion logic — but the column set below is optimized for LLM portfolio analysis. Four columns are required and the run will abort if any are missing: `Account Name`, `Account Number`, `Symbol`, `Current value`. Configure **My View** in the Fidelity positions page before exporting to include these columns. (My View exports the account columns as `Account number` / `Account name` — lowercase second word; `CONTRACT.column_aliases` normalizes them to the canonical names above, so no manual fixup is needed.) An LLM given this data can reason about allocation, cost basis, embedded gains, income, fund costs, and sector exposure in a single pass.

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
- Dist. rate
- Distribution rate as of
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

> Fidelity appends a duplicate summary block at the end of each row repeating cost basis, gain/loss, last price, and change (`Change $` appears twice). With `CONTRACT.drop_duplicate_columns` on (the default), each repeated column (matched ignoring surrounding whitespace and case, e.g. `Last price` / `Last Price`) is dropped when every value equals the first occurrence, and the run aborts if any value differs. Turn it off to keep the copies verbatim.

---

## The Contract

Cleanup rules, footer/disclaimer detection, sectioning, and totals are declared in the `CONTRACT` constant inside `fidelity_csv_to_markdown.py`, a frozen `Contract` dataclass. It used to be a separate YAML file; it's inline so it is versioned, deployed, and invoked together with the code. There is no `--contract` flag.

Input cleanup:

- `column_aliases`: rename incoming columns before processing (e.g. My View's `Account number` → `Account Number`).
- `drop_columns`: remove columns from the output entirely.
- `drop_rows`: `DropRow(column, regex)` rules; rows whose column matches (`re.match`) are dropped. Empty by default.
- `drop_duplicate_columns`: drop repeated headers whose values all match the first occurrence; abort on any mismatch.
- `footer_markers`: case-insensitive substrings that mark disclaimer/footer rows for removal, matched anywhere in the row (including `date downloaded`, so the footer goes regardless of column order). Never use generic brand tokens like `fidelity`, which appear in security names.

Output:

- `heading_template`: each section's H2 heading and account-index line, built from that account's first row (default `{Account Name} ({Account Number})`). Sections are always grouped by `Account Number`, in first-seen order.
- `summary_header`, `as_of_pattern`, `portfolio_totals`: the **portfolio** header. `as_of_pattern` is a case-insensitive regex searched across every cell *before* any rows are dropped (first capture group emitted verbatim). Each `Total(label, column)` sums that column across **all** accounts.
- `account_index`, `account_index_label`, `account_index_column`: list each account with its own subtotal.
- `section_header`, `section_totals`: the **per-account** subtotal under each section heading.

Sums are exact (`Decimal`). Blank and `--` cells are skipped silently; any other cell that doesn't parse as currency is skipped **with a warning** naming it, and a missing column warns and skips that line. All totals are plain pass-through aggregations; see CLAUDE.md "Carve-out for plain aggregation" for the policy boundary.

To adapt to a different CSV layout, edit `CONTRACT`; the conversion functions should not need to change. Mistakes fail loudly as soon as the script loads: a mistyped field name or a wrong-typed value (e.g. `("Sector")` missing its tuple comma) raises `TypeError`, and an invalid regex raises `re.error`.

Cell values are passed through verbatim with one exception: a literal `|` is escaped as `\|` and line breaks become spaces, since either would break the markdown table.

---

## Tests

Pytest suite under `tests/` covers `convert_csv()` and CLI behavior. pytest is the only test dependency.

```bash
uv run --with pytest pytest     # or: python3 -m pytest
```

---

## Privacy Note

Fidelity exports contain account numbers and position details. Do not commit CSV exports or generated markdown to version control. Both `*.csv` and `*.md` output files are gitignored by default (README.md and CLAUDE.md are excluded from that rule).
