"""oap.analytics must import only what the dbt virtualenv has installed."""

import ast
import sys
from pathlib import Path

import pytest

ANALYTICS_DIR = Path(__file__).resolve().parents[2] / "src" / "oap" / "analytics"
ALLOWED_THIRD_PARTY = {"numpy", "pandas"}
ALLOWED_OAP = ("oap.engine", "oap.analytics")
TYPE_CHECKING_ONLY = {"duckdb"}


def _is_allowed(module: str, *, type_checking: bool) -> bool:
    top = module.split(".")[0]
    if top in sys.stdlib_module_names or top in ALLOWED_THIRD_PARTY:
        return True
    if type_checking and top in TYPE_CHECKING_ONLY:
        return True
    return any(module == p or module.startswith(p + ".") for p in ALLOWED_OAP)


def _is_type_checking_test(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
    )


def violations(source: str) -> list[str]:
    """Return the imported modules in ``source`` that the rules do not allow."""
    found: list[str] = []

    def visit(nodes: list[ast.stmt], *, type_checking: bool) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    found.append("." * node.level + (node.module or ""))
                    continue
                names = [node.module or ""]
            else:
                names = []
            found.extend(n for n in names if not _is_allowed(n, type_checking=type_checking))
            if isinstance(node, ast.If):
                guarded = _is_type_checking_test(node.test)
                visit(node.body, type_checking=type_checking or guarded)
                visit(node.orelse, type_checking=type_checking)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                visit(node.body, type_checking=type_checking)
            elif isinstance(node, ast.Try):
                for block in (node.body, node.orelse, node.finalbody):
                    visit(block, type_checking=type_checking)
                for handler in node.handlers:
                    visit(handler.body, type_checking=type_checking)

    visit(ast.parse(source).body, type_checking=False)
    return found


def test_the_package_has_the_expected_modules() -> None:
    names = {p.stem for p in ANALYTICS_DIR.glob("*.py")}
    assert {"__init__", "config", "sample", "backtest", "scoring", "io"} <= names


@pytest.mark.parametrize("path", sorted(ANALYTICS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_module_imports_only_allowed_packages(path: Path) -> None:
    assert violations(path.read_text()) == []


@pytest.mark.parametrize(
    "source",
    [
        "import duckdb",
        "from oap.ingest.writer import write_partition",
        "from oap.quality import gates",
        "import oap.calendar",
        "from oap import calendar",
        "import pyarrow as pa",
        "from . import config",
        "def f():\n    import httpx",
    ],
)
def test_checker_flags_forbidden_imports(source: str) -> None:
    assert violations(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "import math\nimport numpy as np\nimport pandas as pd",
        "from oap.engine.calibration import CalibrationMap",
        "from oap.analytics.config import DEFAULT_CONFIG",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import duckdb",
    ],
)
def test_checker_accepts_allowed_imports(source: str) -> None:
    assert violations(source) == []
