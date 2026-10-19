"""Airflow Datasets that chain the DAGs: bronze, then gold, then the analytics.

They live apart from any DAG module so a producer never imports another DAG. A producer
task lists the Dataset in ``outlets`` and Airflow records an update when that task succeeds;
``dbt_build`` is scheduled on the bronze Datasets, so it runs after bronze has changed, and
``score_spreads`` is scheduled on ``GOLD``, so it runs after ``dbt_build`` has passed its tests.
The URIs are identifiers only (Airflow never reads them): ``iceberg://<catalog>/<namespace>/<table>``
for bronze and ``duckdb://oap/<schema>`` for the DuckDB layers.
"""

from airflow.datasets import Dataset

BRONZE_OPTION_CHAIN = Dataset("iceberg://oap/bronze/option_chain")
"""``bronze.option_chain``: updated after the daily gate passes and after a backfill."""

BRONZE_UNDERLYING_PRICE = Dataset("iceberg://oap/bronze/underlying_price")
"""``bronze.underlying_price``: updated by the price DAGs (the daily one if a slice changed)."""

GOLD = Dataset("duckdb://oap/gold")
"""The gold marts, built and tested: updated by ``publish_gold`` of ``dbt_build`` after a build."""

GOLD_ANALYTICS = Dataset("duckdb://oap/gold/analytics")
"""The calibration tables and spread scores: updated by the analytics task of ``score_spreads``."""
