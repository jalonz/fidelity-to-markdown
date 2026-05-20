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

Output files are named `{account_name}__{account_number}.md`.

---

## Architecture

Single-script ETL pipeline per data source. Each script is paired with a YAML contract — do not share contracts across scripts.

**Data flow:**
1. Read CSV with `dtype=str` — all values preserved as strings, no coercion
2. Load YAML contract (column aliases, drop rules, footer markers, validation policy)
3. Apply `column_aliases` (rename); drop rows matching contract regex rules; drop columns in `drop_columns`; strip footer/disclaimer rows
4. Verify integrity: required columns present, no positions lost (uses `Counter` to catch duplicate holdings), non-zero rows, non-empty account identifiers
5. Write one markdown file per input CSV via `DataFrame.to_markdown(index=False)`, named from the first row's `Account Name` / `Account Number`. The script does not split multi-account CSVs — callers must export one account per CSV.

**Contract-driven design** is load-bearing. Cleanup rules, footer detection, and validation policy live in the YAML contract — not in script logic. When adapting to a different CSV layout, update the contract. Do not encode layout assumptions into the script.

**String preservation is intentional.** Fidelity formats values like `$1,234.56` and `+5.23%` — coercing these to floats drops signal the LLM needs. Do not add numeric parsing unless it's explicitly behind a flag and off by default.

**Fail-fast on integrity breach.** Validation runs fully in-memory before any file is written. `AssertionError` on breach. When a contract `drop_rows` or `drop_columns` rule references a column that isn't in the CSV, a warning goes to stderr and the rule is skipped — this is intentional for forward compatibility with new Fidelity export layouts. Required columns (`Account Name`, `Account Number`, `Symbol`, `Current value`) are not subject to this leniency; missing any of them aborts the run.

---

## Validation workflow

Automated test suite under `tests/` covers `convert_csv()` directly plus CLI behavior via subprocess. Install dev deps and run:

```bash
pip install -r requirements-dev.txt
pytest
```

The suite exercises the happy path, every validation assert (multi-account, output collision, missing required columns, empty post-cleanup, positions lost during cleanup), and CLI ergonomics (mutex `--verbose`/`--quiet`, structured error output, case-insensitive `--csvdir` glob). Fixture lives at `tests/fixtures/fidelity_positions_test.csv`; add more fixtures alongside as needed. Do not commit real Fidelity CSVs as fixtures — anonymize or synthesize them.

For manual spot-checking after a contract change, `--verbose` traces block-level processing.

---

## Constraints

**Dependencies:** Keep the dependency surface minimal. Current deps are `pandas`, `tabulate`, `PyYAML`. Do not add heavy dependencies (no `pyarrow`, no `polars`, no `sqlalchemy`) without a strong reason. If you need to add a dep, add it to `requirements.txt` and note why in the PR.

**Scope:** This tool transforms and formats — it does not analyze, score, or annotate. Analysis is the LLM's job. Do not add logic that interprets portfolio data (e.g., flagging drift, computing allocations). Keep the pipeline dumb and the output faithful.

**New scripts:** If adding a new ETL script for a different data source or output format, create a new script and a new contract. Do not extend `fidelity_csv_to_markdown.py` to handle unrelated sources.

**Privacy:** Do not commit Fidelity CSV exports or generated markdown. Both should be gitignored.
