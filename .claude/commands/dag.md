---
description: Create a new Airflow DAG that uses the project defaults, with a load test
argument-hint: <dag_id> [schedule]
---

Create a new Airflow DAG. Arguments: `$ARGUMENTS` (first word is the `dag_id`, the optional
second is the schedule, e.g. `@daily` or a cron string; default `None`, triggered by hand).

1. Read `dags/common.py` and `dags/smoke.py` and match their style.
2. Create `dags/<dag_id>.py`:
   - A module docstring stating what the DAG does, its schedule, and what it reads and writes.
   - `from dags.common import DEFAULT_ARGS` and pass `default_args=DEFAULT_ARGS`. Override a
     key only when this DAG needs it, and say why in a comment.
   - `@dag(dag_id="<dag_id>", schedule=<schedule>, start_date=datetime(..., tzinfo=UTC),
     catchup=False, tags=[...])`. The start date is timezone-aware UTC.
   - Tasks are `@task` functions with typed signatures and Google-style docstrings. Keep task
     bodies thin: call into `src/oap/` for any real logic so it can be unit tested without
     Airflow.
   - No placeholder tasks or TODOs. If a step cannot be built yet, leave it out.
3. Add `tests/dags/test_<dag_id>.py` that loads the `DagBag` the same way as
   `tests/dags/test_dag_import.py` (reuse its fixture pattern) and asserts `import_errors == {}`,
   `"<dag_id>" in dagbag.dag_ids`, and the expected task ids.
4. Run `make check` and fix anything it reports. Paste its tail in your reply.
