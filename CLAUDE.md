# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

A CLI ETL pipeline that converts Fidelity "Positions" CSV exports into LLM-ready markdown tables. The output is intended to be provided directly to Claude, ChatGPT, or similar tools for portfolio analysis — allocation review, embedded gain analysis, expense ratio auditing, etc.

The output consumer is an LLM. This shapes every formatting and fidelity decision: values must be preserved as strings (no numeric coercion), column names must match what Fidelity exports verbatim, and the markdown must be clean enough to parse without preprocessing.

---

## Setup

The script carries PEP 723 inline metadata, so with [uv](https://docs.astral.sh/uv/) installed there is nothing to set up — `uv run` (or executing the script directly) resolves `pandas` + `tabulate` into a cached ephemeral env.

Without uv, use a venv:
```bash
./setup_env.sh          # create .venv and install requirements.txt
source activate_env.sh  # activate venv (subsequent sessions)
```

If you change dependencies, update both the `# /// script` block and `requirements.txt`.

---

## Running the pipeline

Single file:
```bash
uv run fidelity_csv_to_markdown.py --csv positions.csv   # or: ./fidelity_csv_to_markdown.py / python fidelity_csv_to_markdown.py
```

Batch (all CSVs in a directory):
```bash
uv run fidelity_csv_to_markdown.py --csvdir ./exports/
```

Key flags: `--dry-run` (validate without writing), `--verbose` (detailed block output per file), `--quiet` (errors only), `--outdir DIR` (override output location; default is alongside each input CSV).

Each input CSV produces one output file, named from the input CSV stem (e.g. `Portfolio_Positions_Jun-06-2026.md`). Multi-account exports are grouped into one section per account; single-account exports are the N=1 case.

---

## Architecture

Single-script ETL pipeline per data source. Each script carries its own inline contract — the `CONTRACT` constant, a frozen `Contract` dataclass in the script. There is no external contract file and no `--contract` flag; the contract is versioned, shipped, and invoked with the code (one `__version__`, history in `CHANGELOG.md`). Do not share contracts across scripts.

**Data flow:**
1. Read CSV with `csv.reader` and build the DataFrame directly — every cell is a string by construction, no coercion, no NaN; header names verbatim (Fidelity's duplicated summary-block headers stay duplicated); rows padded/truncated to header width
2. Apply `column_aliases` (rename); if `drop_duplicate_columns`, remove each column whose header repeats an earlier one (ignoring surrounding whitespace and case), keeping the first occurrence verbatim — this happens before any `df[col]` lookup so a repeated required column can't become ambiguous; drop rows matching contract regex rules; drop columns in `drop_columns` (by name); strip footer/disclaimer rows; then verify each removed copy matched its kept column on the surviving rows — any mismatch aborts with `AssertionError`
3. Verify integrity: required columns present, no positions lost across all accounts (uses `Counter` to catch duplicate holdings), non-zero rows, and — per account — non-empty account identifiers
4. Group by `Account Number` (first-seen order) and write **one** markdown file per input CSV, named from the input CSV stem. Each account becomes a `## {Account Name} ({Account Number})` section whose table is `DataFrame.to_markdown(index=False)`. A single-account export is just the N=1 case — there is one uniform path. When `CONTRACT.summary_header` is enabled, the file opens with a portfolio header: an `**As of:**` line (from the Fidelity `Date downloaded` footer), one `**<label>:** $X,XXX.XX` line per configured total (default `Total Current Value`, summed from `Current value` across all accounts), and an account index listing each account with its subtotal. `CONTRACT.section_header` adds a per-account subtotal under each heading. Every total is a sum of the export's column values, not a Fidelity-quoted balance. Any one account failing validation aborts the whole file.

**Contract-driven design** is load-bearing. Cleanup rules, footer detection, sectioning, and which totals to emit live in `CONTRACT` as declared data — not in conversion logic. When adapting to a different CSV layout, edit `CONTRACT`. Do not encode layout assumptions into the conversion functions.

**String preservation is intentional.** Fidelity formats values like `$1,234.56` and `+5.23%` — coercing these to floats drops signal the LLM needs. Do not add numeric parsing unless it's explicitly behind a flag and off by default. This includes rendering: `to_markdown()` must keep `disable_numparse=True`, or tabulate rewrites `1.50` → `1.5`.

**Fail-fast on integrity breach.** Validation runs fully in-memory before any file is written. `AssertionError` on breach. When a `CONTRACT.drop_rows` or `drop_columns` rule references a column that isn't in the CSV, a warning goes to stderr and the rule is skipped — this is intentional for forward compatibility with new Fidelity export layouts. Required columns (`Account Name`, `Account Number`, `Symbol`, `Current value`) are not subject to this leniency; missing (or duplicating) any of them aborts the run.

**The contract is checked by construction.** `Contract` is a frozen dataclass with no defaults: a mistyped or missing field raises `TypeError` at import, and `__post_init__` compiles every regex so a bad pattern raises `re.error` at import — a typo can never silently degrade to default behavior. Keep it that way when adding a field: add it to `Contract` without a default, set it in `CONTRACT`, and compile/check anything that could otherwise fail mid-run in `__post_init__`. `convert_csv(..., contract=CONTRACT)` takes the contract as an optional keyword purely as a test seam (`dataclasses.replace(CONTRACT, ...)`); it is not exposed on the CLI.

---

## Validation workflow

Automated test suite under `tests/` covers `convert_csv()` directly plus CLI behavior via subprocess. Install dev deps and run:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

The suite exercises the happy path, multi-account sectioning (per-account subtotals, account index, empty-`Symbol` tolerance), every validation assert (one bad account aborts the file, output collision, missing/duplicated required columns, duplicate-column dedup and mismatch abort, empty post-cleanup, positions lost during cleanup), contract construction failures (mistyped field, bad regex), verbatim numeric strings and duplicate headers, and CLI ergonomics (mutex `--verbose`/`--quiet`, structured error output, case-insensitive `--csvdir` glob). Fixture lives at `tests/fixtures/fidelity_positions_test.csv`; add more fixtures alongside as needed. Do not commit real Fidelity CSVs as fixtures — anonymize or synthesize them.

For manual spot-checking after a `CONTRACT` change, `--verbose` traces block-level processing.

---

## Constraints

**Dependencies:** Keep the dependency surface minimal. Current deps are `pandas` and `tabulate`. Do not add heavy dependencies (no `pyarrow`, no `polars`, no `sqlalchemy`) without a strong reason. If you need to add a dep, add it to both the PEP 723 `# /// script` block and `requirements.txt`, and note why in the PR.

**Scope:** This tool transforms and formats — it does not analyze, score, or annotate. Analysis is the LLM's job. Do not add logic that interprets portfolio data (e.g., flagging drift, computing allocations against targets, recommending rebalances, scoring holdings). Keep the pipeline dumb and the output faithful.

*Carve-out for plain aggregation and metadata pass-through.* Summing a single existing column verbatim (e.g., totaling `Current value` to produce a `Total Current Value` line — the sum of position values in the export, not a Fidelity-quoted account balance) counts as formatting, not analysis — the LLM could do it by hand from the table, the script just saves it the trip. The same sum scoped to one account (a per-account subtotal or account-index amount) or taken across all accounts (the portfolio total) is still a single-column sum and stays inside the carve-out. Preserving metadata Fidelity already emits (e.g., the `Date downloaded` timestamp as an `As of:` header) is faithful pass-through. The line: no ratios, no derived percentages (including any account's share of the portfolio), no comparisons against external targets or benchmarks, no judgments. If it isn't a sum of one column or a value Fidelity already wrote, it belongs to the LLM. Any such aggregation must be contract-driven (declared as a `Total` in `CONTRACT`), not hardcoded in conversion logic.

**New scripts:** If adding a new ETL script for a different data source or output format, create a new script with its own inline contract. Do not extend `fidelity_csv_to_markdown.py` to handle unrelated sources.

**Privacy:** Do not commit Fidelity CSV exports or generated markdown. Both should be gitignored.
