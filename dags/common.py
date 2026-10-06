"""Project-wide defaults shared by every oap DAG.

Every DAG passes ``DEFAULT_ARGS`` as its ``default_args`` so that retries, the task SLA
and failure logging are consistent. ``tests/dags/test_dag_import.py`` enforces this.
"""

import logging
from datetime import timedelta
from typing import Any

from airflow.utils.context import Context

logger = logging.getLogger(__name__)


def log_failure(context: Context) -> None:
    """Log the identity of a failed task instance and the exception that failed it.

    Args:
        context: The Airflow task context passed to ``on_failure_callback``.
    """
    task_instance = context.get("task_instance")
    logger.error(
        "Task failed: dag_id=%s task_id=%s logical_date=%s exception=%r",
        task_instance.dag_id if task_instance else None,
        task_instance.task_id if task_instance else None,
        context.get("logical_date"),
        context.get("exception"),
    )


DEFAULT_ARGS: dict[str, Any] = {
    "owner": "oap",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "sla": timedelta(hours=1),
    "email_on_failure": False,
    "on_failure_callback": log_failure,
}
