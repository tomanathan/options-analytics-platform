"""Airflow Datasets for the bronze tables, shared by the producer DAGs and ``dbt_build``.

They live apart from any DAG module so a producer never imports another DAG. A producer
task lists the Dataset in ``outlets`` and Airflow records an update when that task succeeds;
``dbt_build`` is scheduled on the Datasets, so it runs after bronze has changed. The URIs are
identifiers only (Airflow never reads them): ``iceberg://<catalog>/<namespace>/<table>``.
"""

from airflow.datasets import Dataset

BRONZE_OPTION_CHAIN = Dataset("iceberg://oap/bronze/option_chain")
"""``bronze.option_chain``: updated after the daily gate passes and after a backfill."""

BRONZE_UNDERLYING_PRICE = Dataset("iceberg://oap/bronze/underlying_price")
"""``bronze.underlying_price``: updated by the price DAGs."""
