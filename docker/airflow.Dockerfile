# Airflow image for the local stack: the official image plus the oap package and its runtime
# dependencies. After a dependency change run `make lock-export`, then `make airflow-build`.
FROM apache/airflow:2.11.2-python3.12

# The base image's packages are Airflow's constraint pins (numpy 1.26.4 and cryptography 44
# among them) and win for anything they already provide: replacing them under Airflow's
# providers breaks the providers. oap's direct dependencies and every package the base image
# lacks are installed at the versions in uv.lock (docker/requirements.txt, from `make
# lock-export`) with --no-deps, so the build is reproducible and pip cannot move Airflow's own
# pins (pandas 3 or pyiceberg's SqlCatalog would pull in SQLAlchemy 2, while Airflow 2.11 needs
# 1.4). The `airflow` and `dbt` dependency groups are not installed: the image already is
# Airflow. Two accepted conflicts, both in unused packages: awswrangler's pyarrow<23 (only
# sagemaker_studio imports it) against the pyarrow 25 the Iceberg writer is tested with, and
# sagemaker-studio's numpy<2.3 against the numpy 2.5 that the engine needs and uv.lock pins;
# the gate below fails the build on any other `pip check` finding. If it flags a package that the
# lock should win, add `--prefer-lock <name>` to the script call.
# The image's airflow user belongs to group root (gid 0), as the official image documents.
COPY --chown=airflow:root pyproject.toml README.md LICENSE docker/requirements.txt scripts/image_requirements.py /opt/oap/
COPY --chown=airflow:root src /opt/oap/src
RUN python /opt/oap/image_requirements.py /opt/oap/requirements.txt /opt/oap/pyproject.toml > /tmp/oap-req.txt \
    && pip install --no-cache-dir --no-deps -r /tmp/oap-req.txt \
    && pip install --no-cache-dir --no-deps /opt/oap \
    && rm /tmp/oap-req.txt

# The base image's shell runs with errexit and pipefail, so each step that may exit non-zero
# says so explicitly.
RUN pip check > /tmp/pc.txt 2>&1 || true; \
    grep -v -e '^awswrangler [^ ]* has requirement pyarrow' -e '^sagemaker-studio [^ ]* has requirement numpy' -e '^No broken requirements found' /tmp/pc.txt > /tmp/pc-unexpected.txt || true; \
    if [ -s /tmp/pc-unexpected.txt ]; then cat /tmp/pc-unexpected.txt >&2; exit 1; fi; \
    rm -f /tmp/pc.txt /tmp/pc-unexpected.txt

# dbt runs from its own virtualenv: dbt-core/dbt-snowflake pin protobuf, networkx and cryptography differently from
# Airflow, and no Airflow code imports dbt. Versions are uv.lock's dbt group (docker/requirements-dbt.txt). dbt packages
# and the DuckDB extensions the bronze hook loads (iceberg, avro, sqlite) are fetched here so a DAG run needs no network.
USER root
RUN python -m venv /opt/dbt-venv && mkdir -p /opt/dbt-packages /opt/duckdb-extensions \
    && chown -R airflow:root /opt/dbt-venv /opt/dbt-packages /opt/duckdb-extensions
USER airflow
COPY --chown=airflow:root docker/requirements-dbt.txt dbt/packages.yml dbt/package-lock.yml /opt/dbt-packages/
RUN /opt/dbt-venv/bin/pip install --no-cache-dir --no-deps -r /opt/dbt-packages/requirements-dbt.txt \
    && /opt/dbt-venv/bin/pip check \
    && cd /opt/dbt-packages && printf 'name: oap_packages\nversion: "1.0.0"\nconfig-version: 2\n' > dbt_project.yml \
    && /opt/dbt-venv/bin/dbt deps --project-dir /opt/dbt-packages \
    && /opt/dbt-venv/bin/python -c "import duckdb; c = duckdb.connect(config={'extension_directory': '/opt/duckdb-extensions'}); [c.install_extension(e) for e in ('iceberg', 'avro', 'sqlite')]" \
    && chmod -R g+rwX /opt/dbt-packages /opt/duckdb-extensions
ENV DBT_PACKAGES_INSTALL_PATH=/opt/dbt-packages/dbt_packages OAP_DUCKDB_EXTENSION_DIR=/opt/duckdb-extensions

# docker-compose.yml mounts ./src at /opt/airflow/src, first on PYTHONPATH, so code edits take
# effect without a rebuild; the installed copy only supplies the dependencies.
