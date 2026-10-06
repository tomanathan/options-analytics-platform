from types import ModuleType

import pytest

import oap
import oap.engine
import oap.engine.implied_distribution
import oap.engine.spread_scoring

ENGINE_MODULES = [
    oap.engine,
    oap.engine.implied_distribution,
    oap.engine.spread_scoring,
]


def test_package_has_docstring() -> None:
    assert oap.__doc__ is not None
    assert oap.__doc__.strip()


@pytest.mark.parametrize("module", ENGINE_MODULES, ids=lambda m: m.__name__)
def test_engine_docstrings_state_units(module: ModuleType) -> None:
    doc = module.__doc__
    assert doc is not None
    assert doc.strip()
    assert "dollars" in doc
    assert "years" in doc
