import tomllib
from pathlib import Path

import oap

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    with PYPROJECT.open("rb") as f:
        project = tomllib.load(f)["project"]
    assert oap.__version__ == project["version"]
