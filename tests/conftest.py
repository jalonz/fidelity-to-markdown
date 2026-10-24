import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from fidelity_csv_to_markdown import CONTRACT, Contract, _read_csv


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "fidelity_positions_test.csv"
MULTI_FIXTURE_CSV = FIXTURE_DIR / "fidelity_positions_multi_account_test.csv"


@dataclass
class Sheet:
    """A raw CSV exactly as the script reads it (verbatim, possibly duplicate
    headers; all-str rows padded to header width, footer rows included), for a
    test to edit and write back. Name lookups take the first occurrence."""
    header: list[str]
    rows: list[list[str]]

    def set(self, column: str, value: str, *, row: int | None = None,
            where: Callable[[dict[str, str]], bool] | None = None) -> None:
        """Set `column` to `value` in one row (by index), in rows matching
        `where` (called with a name -> value dict), or in every row."""
        i = self.header.index(column)
        for n, r in enumerate(self.rows):
            if row is not None and n != row:
                continue
            if where is not None:
                values: dict[str, str] = {}
                for name, val in zip(self.header, r):
                    values.setdefault(name, val)
                if not where(values):
                    continue
            r[i] = value

    def drop(self, column: str) -> None:
        i = self.header.index(column)
        del self.header[i]
        for r in self.rows:
            del r[i]

    def rename(self, old: str, new: str) -> None:
        self.header[self.header.index(old)] = new

    def write(self, path: Path) -> Path:
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([self.header, *self.rows])
        return path


def read_sheet(path: Path) -> Sheet:
    return Sheet(*_read_csv(path))


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
def multi_fixture_sheet() -> Sheet:
    return read_sheet(MULTI_FIXTURE_CSV)


@pytest.fixture
def fixture_sheet() -> Sheet:
    return read_sheet(FIXTURE_CSV)


@pytest.fixture
def write_csv(tmp_path):
    """Factory: write a Sheet to a tmp CSV and return its path."""
    def _write(sheet: Sheet, name: str = "input.csv") -> Path:
        return sheet.write(tmp_path / name)
    return _write
