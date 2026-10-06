import oap.quality
import oap.quality.gates


def test_quality_modules_have_docstrings() -> None:
    for module in (oap.quality, oap.quality.gates):
        assert module.__doc__ is not None
        assert module.__doc__.strip()
