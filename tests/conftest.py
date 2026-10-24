from pathlib import Path

import pandas as pd
import pytest

from fidelity_csv_to_markdown import CONTRACT, Contract, _read_csv as read_raw_csv


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "fidelity_positions_test.csv"
MULTI_FIXTURE_CSV = FIXTURE_DIR / "fidelity_positions_multi_account_test.csv"


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
