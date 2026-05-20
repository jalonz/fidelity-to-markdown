# TODO

Pending work for `fidelity_csv_to_markdown.py`. Items derived from the review session on 2026-05-20.

## Open

- [x] **Bump script version + changelog** (`fidelity_csv_to_markdown.py:5-32`). Header still reads `Version: 2.1.0`. Add a `v2.2.0` entry covering: multi-account guard, output-collision check, mutex `--verbose` / `--quiet`, reformatted argparse error output, `_position_pairs` helper, `ConvertResult` dataclass, and the `_bar` empty-frame fix.
- [x] **README sync**. README documents flags but not the new abort behavior. Add a short note about multi-account rejection and the output-collision check so users aren't surprised by `AssertionError` on inputs that previously "worked".
- [ ] **Automated test suite**. `tests/fixtures/fidelity_positions_test.csv` exists; nothing consumes it. Pytest covering the happy path plus the new asserts (multi-account, collision, missing required column, empty post-cleanup, positions-lost detection) would lock the validation surface in.
- [ ] **CI**. Once a test suite exists, add a GitHub Actions workflow running `pytest` on push and PR.

## Maybe later

- [ ] **`--force` flag** to override the output-collision abort. Only worth adding if the abort gets in the way in practice.
- [ ] **Clean up this file**. Strip the checked items below once they're no longer useful as a session record.

## Maturity (behavior gaps)

- [x] **Detect filename collisions** (`fidelity_csv_to_markdown.py:179-188`). Two CSVs whose `Account Name` / `Account Number` normalize to the same string overwrite each other silently. Check `out_path.exists()` and either error or warn.
- [x] **Reject multi-account CSVs** (`fidelity_csv_to_markdown.py:153-154`). Script names output from `df["Account Name"].iloc[0]` / `df["Account Number"].iloc[0]` — an "All Accounts" export is silently mis-labeled. Assert `df["Account Number"].nunique() == 1` with a clear error.
- [x] **Case-insensitive CSV glob** (`fidelity_csv_to_markdown.py:278`). `d.glob("*.csv")` misses `Positions.CSV` / `Export.Csv`. Replace with `sorted(p for p in d.iterdir() if p.suffix.lower() == ".csv")`.
- [x] **Make `--verbose` and `--quiet` mutually exclusive** (`fidelity_csv_to_markdown.py:249-250`). Both can be passed today; `--quiet` wins silently. Move them into `parser.add_mutually_exclusive_group()`.
- [x] **Unify exception types in validation** (`fidelity_csv_to_markdown.py:148, 163`). Required-column checks raise `KeyError`; everything else raises `AssertionError`. Standardize on `AssertionError` to match the rest of the file.
- [x] **Format CLI usage/error output with newlines**. When invoked with no args or with bad args, argparse's default single-line usage string is hard to scan. Provide a nicely formatted help/error message (custom `format_usage` or a wrapped `error()` override) with line breaks between sections.

## Simplification

- [x] **Snapshot aliased columns directly** (`fidelity_csv_to_markdown.py:99-103`). Replace the comprehension with `list(df.columns)` after the rename. Also drop the `if k in df.columns` filter — pandas silently ignores missing rename keys.
- [x] **Remove redundant `.astype(str)` calls** (`fidelity_csv_to_markdown.py:121, 136`). CSV is read with `dtype=str`, so these are no-ops.
- [x] **Drop unused `prefix` parameter** (`fidelity_csv_to_markdown.py:212, 226`). `print_result_verbose` and `print_result_quiet` both declare `prefix=""` but no caller passes it.
- [x] **Merge required-column checks** (`fidelity_csv_to_markdown.py:146-148, 161-163`). Combine the two passes into one loop over `("Account Name", "Account Number", "Symbol", "Current value")`.
- [x] **Hoist repeated `norm_str` calls** (`fidelity_csv_to_markdown.py:108-112, 165-169`). Each row triggers three `norm_str` calls. Precompute pairs: `pairs = [(norm_str(s), norm_str(v)) for s, v in zip(...)]`, then `Counter(p for p in pairs if any(p))`.
- [x] **Fix dead `A-Z` in `normalize_account_number`** (`fidelity_csv_to_markdown.py:63`). String is already lowercased before the regex; change `[^a-zA-Z0-9]` to `[^a-z0-9]`.

## Lower priority / opinion

- [x] Convert the `convert_csv` result dict to a `@dataclass` for IDE/type support. Pure refactor.
- [x] Cosmetic off-by-one in `_bar` when `filled == 0` on the first frame (renders `[> ...]` with no fill). Harmless.
- [x] Simplify `drop_cols = cleanup.get("drop_columns", []) or []` to `cleanup.get("drop_columns") or []`.
