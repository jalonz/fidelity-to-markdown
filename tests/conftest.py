from pathlib import Path

import pandas as pd
import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "fidelity_positions_test.csv"
MULTI_FIXTURE_CSV = REPO_ROOT / "tests" / "fixtures" / "fidelity_positions_multi_account_test.csv"
CONTRACT_PATH = REPO_ROOT / "fidelity_csv_to_markdown.yaml"


@pytest.fixture
def contract() -> dict:
    with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def fixture_csv_path() -> Path:
    return FIXTURE_CSV


@pytest.fixture
def multi_fixture_csv_path() -> Path:
    return MULTI_FIXTURE_CSV


@pytest.fixture
def multi_fixture_df() -> pd.DataFrame:
    return pd.read_csv(MULTI_FIXTURE_CSV, dtype=str, index_col=False, encoding="utf-8-sig")


@pytest.fixture
def fixture_df() -> pd.DataFrame:
    return pd.read_csv(FIXTURE_CSV, dtype=str, index_col=False, encoding="utf-8-sig")


@pytest.fixture
def write_csv(tmp_path):
    """Factory: write a DataFrame to a tmp CSV and return its path."""
    def _write(df: pd.DataFrame, name: str = "input.csv") -> Path:
        path = tmp_path / name
        df.to_csv(path, index=False)
        return path
    return _write
