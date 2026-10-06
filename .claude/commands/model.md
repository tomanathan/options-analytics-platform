---
description: Create a dbt model with schema.yml descriptions, tests and a docs block
argument-hint: <layer> <model_name>
---

Create a dbt model. Arguments: `$ARGUMENTS` (first word is the layer folder under
`dbt/models/`, e.g. `staging` or `marts`; second is the model name).

1. Read the existing models and `schema.yml` in `dbt/models/<layer>/` and match their style.
2. Create `dbt/models/<layer>/<model_name>.sql`. Select from `ref()` or `source()` only, never
   hard-coded relation names. Write SQL that runs on both DuckDB (`dev`) and Snowflake (`prod`);
   where they differ, use `adapter.dispatch` (ADR 0002).
3. Add the model to `dbt/models/<layer>/schema.yml` (create it if missing) with:
   - `description: "{{ doc('<model_name>') }}"`;
   - every output column listed with a description;
   - at least two `data_tests` across the model, chosen from `unique`, `not_null`,
     `relationships`, `accepted_values` and `dbt_expectations.*`. Put generic test
     arguments under `arguments:`. The model's grain key gets `unique` and `not_null`.
4. Add a `{% docs <model_name> %}` block to `dbt/models/docs.md` describing the grain (what
   one row is) and what the model is for.
5. Run:
   - `uv run dbt compile --project-dir dbt --profiles-dir dbt --target dev`
   - `uv run pytest tests/dbt -q`
   Fix anything that fails and paste the tail of both in your reply.
