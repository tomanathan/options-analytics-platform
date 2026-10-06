"""Smoke DAG: proves the scheduler can parse DAGs and import the oap package.

The DAG has no schedule and is triggered by hand. Its single task imports ``oap`` and
logs the package version, which only succeeds when ``src/`` is on the worker's
PYTHONPATH and the shared defaults in ``dags.common`` import cleanly.
"""

import logging
from datetime import UTC, datetime

from airflow.decorators import dag, task

from dags.common import DEFAULT_ARGS

logger = logging.getLogger(__name__)


@dag(
    dag_id="smoke",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["phase-0"],
)
def smoke() -> None:
    """Import oap on a worker and log its version."""

    @task
    def import_oap() -> str:
        """Import the oap package and return its version string."""
        import oap

        logger.info("oap version %s", oap.__version__)
        return oap.__version__

    import_oap()


smoke()
