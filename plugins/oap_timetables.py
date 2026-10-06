"""Registers the oap timetables with Airflow.

The scheduler and webserver rebuild a DAG's timetable from the serialized DAG by looking
its import path up among the timetables that plugins register. The class is imported from
``dags.timetables``, the same path the DAG files use, so the registered name matches the
serialized one.
"""

from airflow.plugins_manager import AirflowPlugin

from dags.timetables import NYSECloseTimetable


class OapTimetablesPlugin(AirflowPlugin):
    """Plugin exposing ``NYSECloseTimetable`` to the scheduler and webserver."""

    name = "oap_timetables"
    timetables = [NYSECloseTimetable]
