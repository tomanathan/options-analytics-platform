FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir \
        "dbt-core==1.12.5" \
        "dbt-duckdb==1.11.0" \
        "dbt-snowflake==1.12.1" \
    && useradd --create-home --uid 1000 dbt \
    && mkdir -p /workspace \
    && chown dbt:dbt /workspace

USER dbt
WORKDIR /workspace/dbt

ENTRYPOINT ["dbt"]
