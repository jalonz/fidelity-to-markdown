import csv
from pathlib import Path

import pandas as pd
import pytest

from fidelity_csv_to_markdown import CONTRACT, Contract


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "fidelity_positions_test.csv"
MULTI_FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "fidelity_positions_multi_account_test.csv"


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Load a fixture the way the script reads a CSV: csv.reader, verbatim
    (possibly duplicate) headers, all-str cells padded to header width.
    pd.read_csv would mangle duplicate headers to "X.1" and blanks to NaN."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        header, *rows = list(csv.reader(f))
    width = len(header)
    return pd.DataFrame([(r + [""] * width)[:width] for r in rows if r], columns=header)


@pytest.fixture
def contract() -> Contract:
    return CONTRACT


@pytest.fixture
def fixture_csv_path() -> Path:
    return FIXTURE_CSV


@pytest.fixture
def multi_fixture_csv_path() -> Path:
    return MULTI_FIXTURE_CSV


@pytest.fixture
def multi_fixture_df() -> pd.DataFrame:
    return read_raw_csv(MULTI_FIXTURE_CSV)


@pytest.fixture
def fixture_df() -> pd.DataFrame:
    return read_raw_csv(FIXTURE_CSV)


@pytest.fixture
def write_csv(tmp_path):
    """Factory: write a DataFrame to a tmp CSV and return its path."""
    def _write(df: pd.DataFrame, name: str = "input.csv") -> Path:
        path = tmp_path / name
        df.to_csv(path, index=False)
        return path
    return _write
