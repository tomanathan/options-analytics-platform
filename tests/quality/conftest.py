"""Fixtures for the bronze quality gate.

``bronze_good.parquet`` and ``bronze_broken.parquet`` are written to a temporary directory
from the seeded builders in ``batches.py`` on every run, so no binary fixture is committed.
"""

from pathlib import Path

import pandas as pd
import pytest

from tests.quality.batches import build_broken, build_good, build_history


@pytest.fixture(scope="session")
def bronze_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("bronze_fixtures")
    build_good().to_parquet(directory / "bronze_good.parquet", index=False)
    build_broken().to_parquet(directory / "bronze_broken.parquet", index=False)
    return directory


@pytest.fixture
def history() -> pd.DataFrame:
    return build_history()


@pytest.fixture
def good(bronze_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(bronze_dir / "bronze_good.parquet", dtype_backend="pyarrow")


@pytest.fixture
def broken(bronze_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(bronze_dir / "bronze_broken.parquet", dtype_backend="pyarrow")
