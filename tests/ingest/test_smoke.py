import oap.ingest
import oap.ingest.alpaca
import oap.ingest.dolthub
import oap.ingest.iceberg_writer
import oap.ingest.local_catalog
import oap.ingest.schema


def test_ingest_modules_have_docstrings() -> None:
    for module in (
        oap.ingest,
        oap.ingest.alpaca,
        oap.ingest.dolthub,
        oap.ingest.iceberg_writer,
        oap.ingest.local_catalog,
        oap.ingest.schema,
    ):
        assert module.__doc__ is not None
        assert module.__doc__.strip()
