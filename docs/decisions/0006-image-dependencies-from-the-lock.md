# 0006. Install the Airflow image's dependencies from the lock, below Airflow's pins

Status: Accepted (Phase 2)
Date: 2026-10-19

## Context

The official `apache/airflow:2.11.2-python3.12` image ships Airflow's dependencies at the versions of Airflow's constraints file. Several clash with what `oap` needs: the base image has numpy 1.26.4, the engine is written and tested against numpy 2.x, and `pyproject.toml` requires `numpy>=2.2`. The ingest code is tested with pandas 2.3, pyarrow 25 and pyiceberg 0.12. Airflow 2.11 needs SQLAlchemy 1.4, so nothing in the image may pull in SQLAlchemy 2 (ADR 0005).

The Phase 1 image ran `pip install .`, which resolved the ranges in `pyproject.toml` on the day of the build. Two builds a month apart could contain different versions, and neither was the set that `uv.lock` pins and CI tests. A green `make check` said little about the code that ran in Airflow.

dbt adds a second problem. `dbt-core` and `dbt-snowflake` pin protobuf, networkx and cryptography differently from Airflow, and no Airflow code imports dbt.

## Decision

The image installs from the lock, in three parts.

**Direct dependencies and missing packages come from `uv.lock`.** `make lock-export` writes `docker/requirements.txt` with `uv export` (runtime closure, no dependency groups, no hashes, project excluded). `scripts/image_requirements.py` runs in the base image and selects, from that file, the pins for `oap`'s direct dependencies (`[project].dependencies`) and for every package the base image does not have. These are installed with `pip install --no-deps`, so pip never re-resolves anything and cannot move Airflow's pins.

**Precedence.** A package the base image already ships and that `oap` does not depend on directly keeps Airflow's constraint version. A direct dependency takes the lock's version even when the base has another (numpy 2.5.x replaces 1.26.4). A package can be forced to the lock with `--prefer-lock NAME` in the Dockerfile. Airflow and dbt packages are never taken from the lock; the script refuses them.

**A `pip check` gate.** After the install, the build runs `pip check` and fails on any finding except two, both in packages nothing here imports: `awswrangler` wants pyarrow below 23 (only `sagemaker_studio` uses it) and `sagemaker-studio` wants numpy below 2.3. Any other conflict fails the image build.

**dbt runs in its own virtualenv.** `/opt/dbt-venv` is installed from `docker/requirements-dbt.txt` (the `dbt` group of the lock), again with `--no-deps` and a `pip check`. dbt packages (`dbt deps`) and the DuckDB extensions the bronze hook needs (iceberg, avro, sqlite) are fetched at build time into `/opt/dbt-packages` and `/opt/duckdb-extensions`, so a DAG run needs no network.

`make lock-check` re-runs both exports and fails if either file differs from the committed one. It is part of `make check`, and CI pins the `uv` version so the export text is stable. After any dependency change the sequence is `uv lock`, `make lock-export`, `make airflow-build`.

## Consequences

Good:

- The pandas, pyarrow, pyiceberg, numpy and httpx that run in Airflow are the versions CI tested.
- A stale requirements file fails `make check` instead of surfacing as a runtime difference.
- dbt's dependency set cannot break Airflow's, and the reverse.
- DAG runs of `dbt_build` work offline.

Costs and risks:

- The image is a deliberate mix: Airflow's providers run next to numpy 2.5, which Airflow does not test. The `pip check` gate catches declared conflicts but not behaviour. The tests cover the code `oap` imports; they do not exercise Airflow's providers against numpy 2.5.
- The two accepted `pip check` conflicts are real. If a later change starts importing `awswrangler` or `sagemaker_studio`, they will fail at run time, not at build time.
- `--no-deps` trusts the lock to contain every transitive package. A package missing from the export would be missing from the image; the `pip check` gate is what notices.
- `docker/dbt.Dockerfile`, used by the on-demand `dbt` Compose service, still pins three dbt versions by hand. They match the lock today; nothing enforces it.
- The image build context is restricted by `.dockerignore`, so a change to a file outside its allow-list does not rebuild the image.

## Alternatives considered

**Install every pin in the lock.** Rejected. The lock resolves its packages without regard to Airflow's constraints, so installing all of them replaces packages Airflow's own providers run on (numpy and cryptography among them, as the Dockerfile notes) with versions Airflow does not support. The precedence rule above keeps those packages at Airflow's versions unless `oap` imports them directly.

**Version ranges only (`pip install .`).** Rejected. It is the Phase 1 behaviour and the reason for this record: the build is not reproducible and does not match what CI tested.

**Airflow's constraints file as a pip constraint.** Rejected. The constraints pin numpy to 1.26.4, which contradicts `numpy>=2.2`, so pip would refuse the install. Dropping the pin for numpy alone leaves the same question for every other package, to be answered by hand.

**One shared environment for dbt.** Rejected. The protobuf, networkx and cryptography pins of the dbt adapters differ from Airflow's, and no Airflow code imports dbt.
