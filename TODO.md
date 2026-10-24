# TODO

Pending work for `fidelity_csv_to_markdown.py`.

## Open

_Nothing open._

## Done

- [x] **CI** (v5.0.0). `.github/workflows/tests.yml` runs `python -m pytest` on Python 3.10 and 3.14 for every PR and every push to `main`.
- [x] **Inline the contract** (v4.0.0). YAML contract → `CONTRACT` dataclass in the script; `--contract` and PyYAML removed; PEP 723 metadata for `uv run`.
- [x] **Accept multi-account CSV exports** (v3.0.0). Delivered as one sectioned file per CSV — grouped by `Account Number` with a portfolio header and a `## {Account Name} ({Account Number})` section per account — rather than the originally-sketched one-file-per-account, so an "All Accounts" export feeds straight in and stays a single artifact.

## Maybe later

- [ ] **`--force` flag** to override the output-collision abort. Only worth adding if the abort gets in the way in practice.
