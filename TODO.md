# TODO

Pending work for `fidelity_csv_to_markdown.py`.

## Open

- [ ] **CI**. Add a GitHub Actions workflow running `pytest` on push and PR.
- [ ] **Accept multi-account CSV exports**. Currently rejected via assert — split the input by `Account Number` and emit one markdown file per account, so users can feed an "All Accounts" Fidelity export directly.

## Maybe later

- [ ] **`--force` flag** to override the output-collision abort. Only worth adding if the abort gets in the way in practice.
