{#
  Bronze registration (ADR 0008). dbt reads the Iceberg bronze tables through DuckDB's iceberg_scan.
  Once per invocation this hook reads each table's committed metadata_location from the local
  catalog (a stdlib sqlite file), pins that metadata version, and creates the views
  bronze.option_chain and bronze.underlying_price over it. The model build and its tests therefore
  read the same snapshot. The pinned snapshot is recorded in bronze.registered_snapshot.

  OAP_DBT_SOURCE = iceberg   reads $OAP_ICEBERG_LOCAL_DIR (default .iceberg-local)
                   synthetic reads $OAP_SYNTHETIC_BRONZE_DIR (default .dbt-local/synthetic-iceberg)
                   auto      (default) iceberg if its catalog.db exists, otherwise synthetic
  A missing catalog or table raises a compiler error: the hook fails closed, never silently falls back.
  A DuckDB file built from one mode refuses to build from the other, so synthetic rows never reach
  oap.duckdb. dbt 1.12 runs on-run-start hooks during compile, so the hook is skipped there.
  On Snowflake the sources point at external Iceberg tables and the hook does nothing.
#}
{% macro bronze_source_mode() %}{% set mode = env_var('OAP_DBT_SOURCE', 'auto') | lower %}
  {% if mode not in ['auto','iceberg','synthetic'] %}{% do exceptions.raise_compiler_error("OAP_DBT_SOURCE must be auto, iceberg or synthetic, got '" ~ mode ~ "'") %}{% endif %}
  {{ return(mode) }}{% endmacro %}
{% macro bronze_catalog_dir(mode) %}{% if mode == 'synthetic' %}{{ return(env_var('OAP_SYNTHETIC_BRONZE_DIR', '.dbt-local/synthetic-iceberg')) }}{% endif %}
  {{ return(env_var('OAP_ICEBERG_LOCAL_DIR', '.iceberg-local')) }}{% endmacro %}
{% macro bronze_file_exists(path) %}{{ return(run_query("select count(*) from glob('" ~ path ~ "')").columns[0].values()[0] > 0) }}{% endmacro %}
{% macro register_bronze() %}{{ return(adapter.dispatch('register_bronze', 'oap')()) }}{% endmacro %}
{% macro default__register_bronze() %}{{ return('select 1 as bronze_registered') }}{% endmacro %}
{% macro duckdb__register_bronze() %}
  {% set noop = 'select 1 as bronze_registered' %}
  {% if not execute or flags.WHICH in ['compile','parse','list','ls','docs'] %}{{ return(noop) }}{% endif %}
  {% set mode = bronze_source_mode() %}
  {% if mode == 'auto' %}{% set mode = 'iceberg' if bronze_file_exists(bronze_catalog_dir('iceberg') ~ '/catalog.db') else 'synthetic' %}
    {% do log('OAP_DBT_SOURCE=auto resolved to ' ~ mode, info=True) %}{% endif %}
  {% set dir = bronze_catalog_dir(mode) %}
  {% if not bronze_file_exists(dir ~ '/catalog.db') %}{% do exceptions.raise_compiler_error("bronze catalog " ~ dir ~ "/catalog.db not found (OAP_DBT_SOURCE=" ~ mode ~ "); run `make synthetic-bronze` or set OAP_ICEBERG_LOCAL_DIR") %}{% endif %}
  {% do run_query("install iceberg; load iceberg; install sqlite; load sqlite; create schema if not exists bronze; create table if not exists bronze.registered_snapshot (table_name varchar, metadata_location varchar, mode varchar, registered_at timestamp)") %}
  {% set previous = run_query("select distinct mode from bronze.registered_snapshot") %}
  {% if previous.rows | length > 0 and previous.columns[0].values()[0] != mode %}{% do exceptions.raise_compiler_error("this DuckDB file was built from " ~ previous.columns[0].values()[0] ~ " bronze, this run reads " ~ mode ~ "; set another OAP_DUCKDB_PATH or delete the file") %}{% endif %}
  {% set found = run_query("select table_name, metadata_location from sqlite_scan('" ~ dir ~ "/catalog.db', 'iceberg_tables') where table_namespace = 'bronze'") %}
  {% set locations = {} %}{% for row in found.rows %}{% do locations.update({row[0]: row[1]}) %}{% endfor %}
  {% do run_query("delete from bronze.registered_snapshot") %}
  {% for table in ['option_chain', 'underlying_price'] %}
    {% if table not in locations %}{% do exceptions.raise_compiler_error("bronze." ~ table ~ " is not in " ~ dir ~ "/catalog.db") %}{% endif %}
    {% set version = modules.re.search('/metadata/([^/]+)\.metadata\.json$', locations[table]).group(1) %}
    {% do log('bronze.' ~ table ~ ' <- ' ~ locations[table], info=True) %}
    {% do run_query("create or replace view bronze." ~ table ~ " as select * from iceberg_scan('" ~ dir ~ "/warehouse/bronze/" ~ table ~ "', version = '" ~ version ~ "', allow_moved_paths = true)") %}
    {% do run_query("insert into bronze.registered_snapshot values ('" ~ table ~ "', '" ~ locations[table] ~ "', '" ~ mode ~ "', current_timestamp)") %}
  {% endfor %}
  {{ return(noop) }}
{% endmacro %}
