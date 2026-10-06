import oap.ingest
import oap.ingest.chains


def test_ingest_modules_have_docstrings() -> None:
    for module in (oap.ingest, oap.ingest.chains):
        assert module.__doc__ is not None
        assert module.__doc__.strip()
