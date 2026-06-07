# TODO

Pending work for `fidelity_csv_to_markdown.py`.

## Open

- [ ] **CI**. Add a GitHub Actions workflow running `pytest` on push and PR.

## Done

- [x] **Accept multi-account CSV exports** (v3.0.0). Delivered as one sectioned file per CSV — grouped by `Account Number` with a portfolio header and a `## {Account Name} ({Account Number})` section per account — rather than the originally-sketched one-file-per-account, so an "All Accounts" export feeds straight in and stays a single artifact.

## Maybe later

- [ ] **`--force` flag** to override the output-collision abort. Only worth adding if the abort gets in the way in practice.
