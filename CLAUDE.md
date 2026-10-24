# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

A CLI ETL pipeline that converts Fidelity "Positions" CSV exports into LLM-ready markdown tables. The output is intended to be provided directly to Claude, ChatGPT, or similar tools for portfolio analysis — allocation review, embedded gain analysis, expense ratio auditing, etc.

The output consumer is an LLM. This shapes every formatting and fidelity decision: values must be preserved as strings (no numeric coercion), column names must match what Fidelity exports verbatim, and the markdown must be clean enough to parse without preprocessing.

---

## Setup

None. The script is **standard library only** and needs nothing but Python ≥ 3.10 — run it with `python3` (or directly, via its `python3` shebang). Its PEP 723 `# /// script` block declares the Python version and an empty dependency list, so `uv run` also works but isn't required. Keep it dependency-free: no `requirements*.txt`, venv scripts, or `pyproject.toml`.

---

## Running the pipeline

Single file:
```bash
python3 fidelity_csv_to_markdown.py --csv positions.csv   # or: ./fidelity_csv_to_markdown.py, or uv run ...
```

Batch (all CSVs in a directory):
```bash
python3 fidelity_csv_to_markdown.py --csvdir ./exports/
```

Key flags: `--dry-run` (validate without writing), `--verbose` (detailed block output per file), `--quiet` (errors only), `--outdir DIR` (override output location; default is alongside each input CSV).

Each input CSV produces one output file, named from the input CSV stem (e.g. `Portfolio_Positions_Jun-06-2026.md`). Multi-account exports are grouped into one section per account; single-account exports are the N=1 case.

---

## Architecture

Single-script ETL pipeline per data source. Each script carries its own inline contract — the `CONTRACT` constant, a frozen `Contract` dataclass in the script. There is no external contract file and no `--contract` flag; the contract is versioned, shipped, and invoked with the code (one `__version__`, history in `CHANGELOG.md`). Do not share contracts across scripts.

**Data flow:**
1. Read CSV with `csv.reader` into plain lists (`header`, `rows`) — every cell is a string by construction, no coercion; header names verbatim; short rows (the footer) padded to header width; surplus fields dropped only if empty (trailing commas) — a non-empty surplus field aborts
2. Apply `column_aliases` (rename); if `drop_duplicate_columns`, remove each column whose header repeats an earlier one (ignoring surrounding whitespace and case) from the active columns, keeping the first occurrence verbatim (cleanup works on full-width raw rows plus a list of active column positions, so removed copies can still be verified later); drop rows matching contract regex rules; drop columns in `drop_columns` (by name); strip footer/disclaimer rows (`footer_markers` match anywhere in the row, so the `Date downloaded` footer goes whatever column it lands in); then verify each removed copy matched its kept column on the surviving rows — any mismatch aborts with `AssertionError`
3. Verify integrity: required columns present, no positions lost across all accounts (uses `Counter` to catch duplicate holdings; the baseline counts rows with an `Account Number`), non-zero rows, and — per account — non-empty account identifiers. Totals columns are scanned once: a missing column, or a cell that is neither a currency value nor blank/`--`, warns to stderr (such cells are left out of every total)
4. Group by `Account Number` (first-seen order) and write **one** markdown file per input CSV, named from the input CSV stem. Grouping is always by `Account Number` (structural, not configurable). Each account becomes a `## {heading_template}` section (default `{Account Name} ({Account Number})`, also used for its account-index line) whose table is rendered by `_pipe_table` — byte-for-byte the tabulate "pipe" format earlier versions emitted (cells stripped, headers not, left-aligned, width = max(widest cell, header + 2)), locked by a golden test. A single-account export is just the N=1 case — there is one uniform path. When `CONTRACT.summary_header` is enabled, the file opens with a portfolio header: an `**As of:**` line (from the Fidelity `Date downloaded` footer), one `**<label>:** $X,XXX.XX` line per configured total (default `Total Current Value`, summed from `Current value` across all accounts), and an account index listing each account with its subtotal. `CONTRACT.section_header` adds a per-account subtotal under each heading. Every total is a sum of the export's column values, not a Fidelity-quoted balance. Any one account failing validation aborts the whole file.

**Contract-driven design** is load-bearing. Cleanup rules, footer detection, sectioning, and which totals to emit live in `CONTRACT` as declared data — not in conversion logic. When adapting to a different CSV layout, edit `CONTRACT`. Do not encode layout assumptions into the conversion functions.

**String preservation is intentional.** Fidelity formats values like `$1,234.56` and `+5.23%` — coercing these to floats drops signal the LLM needs. Do not add numeric parsing unless it's explicitly behind a flag and off by default. This includes rendering: `_pipe_table` must never reinterpret a value (tabulate's numparse, used through v4.0.0, rewrote `1.50` → `1.5`). Don't reintroduce pandas or tabulate: pandas' label semantics (duplicate names returning a frame, NaN for blanks) caused real bugs here. The single deliberate exception is markdown safety (`_md_cell`): a literal `|` in a cell or header is escaped as `\|` and line breaks become spaces, because either would otherwise split the table. Totals are summed with `Decimal`, never float.

**Fail-fast on integrity breach.** Validation runs fully in-memory before any file is written. `AssertionError` on breach. When a `CONTRACT.drop_rows` or `drop_columns` rule references a column that isn't in the CSV, a warning goes to stderr and the rule is skipped — this is intentional for forward compatibility with new Fidelity export layouts. Required columns (`Account Name`, `Account Number`, `Symbol`, `Current value`) are not subject to this leniency; missing (or duplicating) any of them aborts the run.

**The contract is checked by construction.** `Contract` is a frozen dataclass with no defaults: a mistyped or missing field raises `TypeError` at import; `__post_init__` checks every field's value against its annotation (`_check_fields` — catches the missing-comma tuple typo `("Sector")`) and compiles every regex so a bad pattern raises `re.error` at import — a typo can never silently degrade to default behavior. Keep it that way when adding a field: add it to `Contract` without a default, using an annotation shape `_check_type` understands (class, `X | None`, `tuple[X, ...]`, `dict[K, V]`), set it in `CONTRACT`, and compile/check anything else that could fail mid-run in `__post_init__`. `convert_csv(..., contract=CONTRACT)` takes the contract as an optional keyword purely as a test seam (`dataclasses.replace(CONTRACT, ...)`); it is not exposed on the CLI.

---

## Validation workflow

Automated test suite under `tests/` covers `convert_csv()` directly plus CLI behavior via subprocess. pytest is the only test dependency:

```bash
uv run --with pytest pytest     # or: python3 -m pytest (with pytest installed)
```

The suite exercises the happy path, multi-account sectioning (per-account subtotals, account index, empty-`Symbol` tolerance), every validation assert (one bad account aborts the file, output collision, missing/duplicated required columns, duplicate-column dedup and mismatch abort, non-empty surplus fields, empty post-cleanup, positions lost during cleanup), contract construction failures (mistyped field, wrong-typed value, bad regex), verbatim numeric strings and duplicate headers, markdown escaping, exact `Decimal` totals and unparseable-cell warnings, and CLI ergonomics (mutex `--verbose`/`--quiet`, structured error output, case-insensitive `--csvdir` glob). Fixture lives at `tests/fixtures/fidelity_positions_test.csv`; add more fixtures alongside as needed. Edit fixtures through conftest's `Sheet` (`fixture_sheet`, `read_sheet`, `write_csv`), which loads them with the script's own `_read_csv`, so tests see exactly what the script sees (verbatim duplicate headers, all-str cells, footer rows). Do not commit real Fidelity CSVs as fixtures — anonymize or synthesize them.

For manual spot-checking after a `CONTRACT` change, `--verbose` traces block-level processing.

---

## Constraints

**Dependencies:** None — standard library only, by design (v5.0.0 removed pandas and tabulate: 106 MB of environment and ~0.24 s of import time for list filtering and a pipe table). Adding any dependency needs a strong reason; if you add one, declare it in the PEP 723 `# /// script` block (the only place deps are declared), switch the shebang back to `uv run --script`, and note why in the PR.

**Scope:** This tool transforms and formats — it does not analyze, score, or annotate. Analysis is the LLM's job. Do not add logic that interprets portfolio data (e.g., flagging drift, computing allocations against targets, recommending rebalances, scoring holdings). Keep the pipeline dumb and the output faithful.

*Carve-out for plain aggregation and metadata pass-through.* Summing a single existing column verbatim (e.g., totaling `Current value` to produce a `Total Current Value` line — the sum of position values in the export, not a Fidelity-quoted account balance) counts as formatting, not analysis — the LLM could do it by hand from the table, the script just saves it the trip. The same sum scoped to one account (a per-account subtotal or account-index amount) or taken across all accounts (the portfolio total) is still a single-column sum and stays inside the carve-out. Preserving metadata Fidelity already emits (e.g., the `Date downloaded` timestamp as an `As of:` header) is faithful pass-through. The line: no ratios, no derived percentages (including any account's share of the portfolio), no comparisons against external targets or benchmarks, no judgments. If it isn't a sum of one column or a value Fidelity already wrote, it belongs to the LLM. Any such aggregation must be contract-driven (declared as a `Total` in `CONTRACT`), not hardcoded in conversion logic.

**New scripts:** If adding a new ETL script for a different data source or output format, create a new script with its own inline contract. Do not extend `fidelity_csv_to_markdown.py` to handle unrelated sources.

**Privacy:** Do not commit Fidelity CSV exports or generated markdown. Both should be gitignored.
