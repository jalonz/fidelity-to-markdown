# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

A CLI ETL pipeline that converts Fidelity brokerage positions CSV exports into LLM-ready markdown tables. The output is intended to be provided directly to Claude, ChatGPT, or similar tools for portfolio analysis — allocation review, embedded gain analysis, expense ratio auditing, etc.

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
python fidelity_csv_to_markdown.py --csv positions.csv --contract fidelity_csv_to_markdown.yaml --outdir ./out
```

Batch (all CSVs in a directory):
```bash
python fidelity_csv_to_markdown.py --csvdir ./exports/ --contract fidelity_csv_to_markdown.yaml --outdir ./out
```

Key flags: `--dry-run` (validate without writing), `--verbose` (detailed block output per file), `--quiet` (errors only).

Output files are named `{account_name}__{account_number}.md`.

---

## Architecture

Single-script ETL pipeline per data source. Each script is paired with a YAML contract — do not share contracts across scripts.

**Data flow:**
1. Read CSV with `dtype=str` — all values preserved as strings, no coercion
2. Load YAML contract (drop rules, footer markers, validation policy)
3. Drop rows matching contract regex rules; strip footer/disclaimer rows
4. Verify integrity: required columns present, no positions lost (uses `Counter` to catch duplicate holdings), non-zero rows, non-empty account identifiers
5. Write one markdown file per account via `DataFrame.to_markdown(index=False)`

**Contract-driven design** is load-bearing. Cleanup rules, footer detection, and validation policy live in the YAML contract — not in script logic. When adapting to a different CSV layout, update the contract. Do not encode layout assumptions into the script.

**String preservation is intentional.** Fidelity formats values like `$1,234.56` and `+5.23%` — coercing these to floats drops signal the LLM needs. Do not add numeric parsing unless it's explicitly behind a flag and off by default.

**Fail-fast on integrity breach.** Validation runs fully in-memory before any file is written. `AssertionError` on breach. Missing-column warnings go to stderr and do not abort — this is intentional for forward compatibility with new Fidelity export layouts.

---

## Validation workflow

There is no automated test suite. Validate changes manually:

1. Run `--dry-run` against a known-good CSV and confirm no assertion errors
2. Run normally and inspect the output markdown — verify row count matches source, column names are correct, no values are coerced or truncated
3. For contract changes, run `--verbose` to trace block-level processing

If you add a test suite, use `pytest` and keep fixtures in `tests/fixtures/`. Do not commit real Fidelity CSVs as fixtures — anonymize or synthesize them.

---

## Constraints

**Dependencies:** Keep the dependency surface minimal. Current deps are `pandas`, `tabulate`, `PyYAML`. Do not add heavy dependencies (no `pyarrow`, no `polars`, no `sqlalchemy`) without a strong reason. If you need to add a dep, add it to `requirements.txt` and note why in the PR.

**Scope:** This tool transforms and formats — it does not analyze, score, or annotate. Analysis is the LLM's job. Do not add logic that interprets portfolio data (e.g., flagging drift, computing allocations). Keep the pipeline dumb and the output faithful.

**New scripts:** If adding a new ETL script for a different data source or output format, create a new script and a new contract. Do not extend `fidelity_csv_to_markdown.py` to handle unrelated sources.

**Privacy:** Do not commit Fidelity CSV exports or generated markdown. Both should be gitignored.
