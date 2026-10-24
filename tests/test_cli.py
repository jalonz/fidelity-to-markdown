import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "fidelity_csv_to_markdown.py"


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_no_args_shows_structured_error():
    proc = run_cli()
    assert proc.returncode == 2
    assert "ERROR:" in proc.stderr
    assert "Usage:" in proc.stderr
    assert "--help" in proc.stderr


def test_mutex_verbose_and_quiet_rejected():
    proc = run_cli("--csv", "x", "--verbose", "--quiet")
    assert proc.returncode == 2
    assert "not allowed with argument --verbose" in proc.stderr
    assert "ERROR:" in proc.stderr


def test_unknown_flag_shows_error():
    proc = run_cli("--csv", "x", "--bogus")
    assert proc.returncode == 2
    assert "unrecognized arguments: --bogus" in proc.stderr


def test_help_exits_zero():
    proc = run_cli("--help")
    assert proc.returncode == 0
    assert "usage:" in proc.stdout.lower()


def test_happy_path_dry_run_exits_zero(fixture_csv_path, tmp_path):
    proc = run_cli(
        "--csv", str(fixture_csv_path),
        "--outdir", str(tmp_path),
        "--dry-run",
    )
    assert proc.returncode == 0, proc.stderr
    # Output filename now derives from the input CSV stem.
    assert "fidelity_positions_test.md" in proc.stdout


def test_case_insensitive_csvdir_glob(fixture_csv_path, tmp_path):
    # Copy fixture with an uppercase .CSV extension; --csvdir should still pick it up.
    target = tmp_path / "Positions.CSV"
    shutil.copy(fixture_csv_path, target)

    proc = run_cli(
        "--csvdir", str(tmp_path),
        "--outdir", str(tmp_path),
        "--dry-run",
    )
    assert proc.returncode == 0, proc.stderr
    # Stem-based output name preserves the input file's case ("Positions.CSV").
    assert "Positions.md" in proc.stdout


def test_contract_flag_removed(fixture_csv_path):
    # The contract is inline; an external contract can no longer be supplied.
    proc = run_cli("--csv", str(fixture_csv_path), "--contract", "x.yaml", "--dry-run")
    assert proc.returncode == 2
    assert "unrecognized arguments: --contract" in proc.stderr


def test_multi_account_cli_end_to_end(multi_fixture_csv_path, tmp_path):
    proc = run_cli(
        "--csv", str(multi_fixture_csv_path),
        "--outdir", str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "fidelity_positions_multi_account_test.md"
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "## Brokerage - TOD (ACCT-AAA)" in body
    assert "## Rollover IRA (ACCT-BBB)" in body
    assert "## 401(k) Plan (ACCT-CCC)" in body
    assert "**Total Current Value:** $115,000.00" in body
