# fidelity-to-markdown

Converts Fidelity CSV exports into LLM-ready markdown for portfolio analysis.

The intended workflow: export your positions from Fidelity → run the script → provide the markdown output to Claude, ChatGPT, or another LLM for analysis (allocation review, tax lot examination, drift detection, etc.). The script preserves all values as strings — no numeric coercion — so the LLM sees exactly what Fidelity shows.

---

## Scripts

### `fidelity_csv_to_markdown.py`

Converts a Fidelity positions CSV export into one markdown table per account. Supports single-file and batch (directory) mode. Each output file is named `{account_name}__{account_number}.md`.

> Additional scripts may be added as the ETL surface expands. Each script owns its own contract file — they are not shared.

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

Single file:
```bash
python fidelity_csv_to_markdown.py \
  --csv path/to/positions.csv \
  --contract fidelity_csv_to_markdown.yaml \
  --outdir ./out
```

Batch (all CSVs in a directory):
```bash
python fidelity_csv_to_markdown.py \
  --csvdir path/to/exports/ \
  --contract fidelity_csv_to_markdown.yaml \
  --outdir ./out
```

**Arguments:**

| Argument | Required | Description |
| --- | --- | --- |
| `--csv` | Yes (or `--csvdir`) | Single Fidelity positions CSV |
| `--csvdir` | Yes (or `--csv`) | Directory of CSVs to process |
| `--contract` | Yes | Path to the YAML contract file |
| `--outdir` | No | Output directory (default: current dir for `--csv`; alongside each input file for `--csvdir`) |
| `--dry-run` | No | Validate without writing output |
| `--verbose` | No | Detailed block output per file instead of one-line summary |
| `--quiet` | No | Suppress all output except errors |

---

## Fidelity Portal Column Selection

The script is contract-driven — it works with whatever columns are present — but the column set below is optimized for LLM portfolio analysis. Configure **My View** in the Fidelity positions page before exporting to include these columns. An LLM given this data can reason about allocation, cost basis, embedded gains, income, fund costs, and sector exposure in a single pass.

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

To adapt the pipeline to a different CSV layout or add cleanup rules, update the contract — the script logic should not need to change.

---

## Privacy Note

Fidelity exports contain account numbers and position details. Do not commit CSV exports or generated markdown to version control. Both `*.csv` and `out/` are gitignored by default.
