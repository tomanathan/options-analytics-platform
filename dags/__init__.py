"""Airflow DAGs for the options analytics platform.

Shared defaults live in ``dags.common``; every DAG module imports them so retry, SLA and
failure alerting behaviour is the same across pipelines.
"""
