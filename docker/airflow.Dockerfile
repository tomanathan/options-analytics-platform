# Airflow image for the local stack: the official image plus the oap package and its runtime
# dependencies. Rebuild with `make airflow-build` whenever pyproject.toml's dependencies change.
FROM apache/airflow:2.11.2-python3.12

# The project pins pandas<3 and installs pyiceberg without the sql-sqlite extra (the local
# catalog is stdlib sqlite3) precisely so this install leaves Airflow's own pins alone:
# pandas 3 and pyiceberg's SqlCatalog would pull in SQLAlchemy 2, while Airflow 2.11 needs 1.4.
# Naming apache-airflow at the image's version makes pip treat it as a constraint rather than
# something it may up- or downgrade. The `airflow` dependency group is not installed: the
# image already is Airflow.
# The image's airflow user belongs to group root (gid 0), as the official image documents.
COPY --chown=airflow:root pyproject.toml README.md LICENSE /opt/oap/
COPY --chown=airflow:root src /opt/oap/src
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" /opt/oap

# docker-compose.yml mounts ./src at /opt/airflow/src, first on PYTHONPATH, so code edits take
# effect without a rebuild; the installed copy only supplies the dependencies.
