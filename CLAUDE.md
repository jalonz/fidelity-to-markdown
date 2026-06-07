# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

A CLI ETL pipeline that converts Fidelity "Positions" CSV exports into LLM-ready markdown tables. The output is intended to be provided directly to Claude, ChatGPT, or similar tools for portfolio analysis — allocation review, embedded gain analysis, expense ratio auditing, etc.

The output consumer is an LLM. This shapes every formatting and fidelity decision: values must be preserved as strings (no numeric coercion), column names must match what Fidelity exports verbatim, and the markdown must be clean enough to parse without preprocessing.

---

## Setup

```bash
./setup_env.sh          # create .venv and install dependencies
source activate_env.sh  # activate venv (subsequent sessions)
```

---

## Running the pipeline

Single file:
```bash
python fidelity_csv_to_markdown.py --csv positions.csv --contract fidelity_csv_to_markdown.yaml
```

Batch (all CSVs in a directory):
```bash
python fidelity_csv_to_markdown.py --csvdir ./exports/ --contract fidelity_csv_to_markdown.yaml
```

Key flags: `--dry-run` (validate without writing), `--verbose` (detailed block output per file), `--quiet` (errors only), `--outdir DIR` (override output location; default is alongside each input CSV).

Each input CSV produces one output file, named from the input CSV stem (e.g. `Portfolio_Positions_Jun-06-2026.md`). Multi-account exports are grouped into one section per account; single-account exports are the N=1 case.

---

## Architecture

Single-script ETL pipeline per data source. Each script is paired with a YAML contract — do not share contracts across scripts.

**Data flow:**
1. Read CSV with `dtype=str` — all values preserved as strings, no coercion
2. Load YAML contract (column aliases, drop rules, footer markers, validation policy)
3. Apply `column_aliases` (rename); drop rows matching contract regex rules; drop columns in `drop_columns`; strip footer/disclaimer rows
4. Verify integrity: required columns present, no positions lost across all accounts (uses `Counter` to catch duplicate holdings), non-zero rows, and — per account — non-empty account identifiers
5. Group by `Account Number` (first-seen order) and write **one** markdown file per input CSV, named from the input CSV stem. Each account becomes a `## {Account Name} ({Account Number})` section whose table is `DataFrame.to_markdown(index=False)`. A single-account export is just the N=1 case — there is one uniform path. When `output.markdown.summary_header` is enabled, the file opens with a portfolio header: an `**As of:**` line (from the Fidelity `Date downloaded` footer), one `**<label>:** $X,XXX.XX` line per configured total (default `Total Current Value`, summed from `Current value` across all accounts), and an account index listing each account with its subtotal. `section_header` adds a per-account subtotal under each heading. Every total is a sum of the export's column values, not a Fidelity-quoted balance. Any one account failing validation aborts the whole file.

**Contract-driven design** is load-bearing. Cleanup rules, footer detection, and validation policy live in the YAML contract — not in script logic. When adapting to a different CSV layout, update the contract. Do not encode layout assumptions into the script.

**String preservation is intentional.** Fidelity formats values like `$1,234.56` and `+5.23%` — coercing these to floats drops signal the LLM needs. Do not add numeric parsing unless it's explicitly behind a flag and off by default.

**Fail-fast on integrity breach.** Validation runs fully in-memory before any file is written. `AssertionError` on breach. When a contract `drop_rows` or `drop_columns` rule references a column that isn't in the CSV, a warning goes to stderr and the rule is skipped — this is intentional for forward compatibility with new Fidelity export layouts. Required columns (`Account Name`, `Account Number`, `Symbol`, `Current value`) are not subject to this leniency; missing any of them aborts the run.

**The contract itself is schema-checked at load** (`validate_contract`, invoked in `main()` before any file is read). Unknown keys, wrong types, and uncompilable regexes in the behavior-bearing subtrees (`contract`, `input_cleanup`, `output.markdown` and below) abort the run with a list of problems, rather than silently degrading to default behavior — a typo'd `heading_template` should fail loudly, not quietly drop the section heading. Note the deliberate asymmetry with the column-reference leniency above: that leniency is for runtime *data* references (forward-compat with new export layouts), whereas contract *keys* are structural and a mistyped one is always an error. Descriptive metadata (`changelog`, `task`, `input`, `constraints`) is not policed. The check is hand-rolled (no schema dependency) and lives next to the config accessors it guards; extend it when you add a contract key.

---

## Validation workflow

Automated test suite under `tests/` covers `convert_csv()` directly plus CLI behavior via subprocess. Install dev deps and run:

```bash
pip install -r requirements-dev.txt
pytest
```

The suite exercises the happy path, multi-account sectioning (per-account subtotals, account index, empty-`Symbol` tolerance), every validation assert (one bad account aborts the file, output collision, missing required columns, empty post-cleanup, positions lost during cleanup), and CLI ergonomics (mutex `--verbose`/`--quiet`, structured error output, case-insensitive `--csvdir` glob). Fixture lives at `tests/fixtures/fidelity_positions_test.csv`; add more fixtures alongside as needed. Do not commit real Fidelity CSVs as fixtures — anonymize or synthesize them.

For manual spot-checking after a contract change, `--verbose` traces block-level processing.

---

## Constraints

**Dependencies:** Keep the dependency surface minimal. Current deps are `pandas`, `tabulate`, `PyYAML`. Do not add heavy dependencies (no `pyarrow`, no `polars`, no `sqlalchemy`) without a strong reason. If you need to add a dep, add it to `requirements.txt` and note why in the PR.

**Scope:** This tool transforms and formats — it does not analyze, score, or annotate. Analysis is the LLM's job. Do not add logic that interprets portfolio data (e.g., flagging drift, computing allocations against targets, recommending rebalances, scoring holdings). Keep the pipeline dumb and the output faithful.

*Carve-out for plain aggregation and metadata pass-through.* Summing a single existing column verbatim (e.g., totaling `Current value` to produce a `Total Current Value` line — the sum of position values in the export, not a Fidelity-quoted account balance) counts as formatting, not analysis — the LLM could do it by hand from the table, the script just saves it the trip. The same sum scoped to one account (a per-account subtotal or account-index amount) or taken across all accounts (the portfolio total) is still a single-column sum and stays inside the carve-out. Preserving metadata Fidelity already emits (e.g., the `Date downloaded` timestamp as an `As of:` header) is faithful pass-through. The line: no ratios, no derived percentages (including any account's share of the portfolio), no comparisons against external targets or benchmarks, no judgments. If it isn't a sum of one column or a value Fidelity already wrote, it belongs to the LLM. Any such aggregation must be contract-driven (configured in YAML), not hardcoded.

**New scripts:** If adding a new ETL script for a different data source or output format, create a new script and a new contract. Do not extend `fidelity_csv_to_markdown.py` to handle unrelated sources.

**Privacy:** Do not commit Fidelity CSV exports or generated markdown. Both should be gitignored.
