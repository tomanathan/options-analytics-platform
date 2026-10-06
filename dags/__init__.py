"""Airflow DAGs for the options analytics platform.

Shared defaults live in ``dags.common``; every DAG module imports them so retries, the task
SLA and failure logging are the same across pipelines.
"""
