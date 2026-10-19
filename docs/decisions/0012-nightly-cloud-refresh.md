# 0012. Refresh the data nightly in GitHub Actions, keeping the warehouse in the Actions cache

Status: Accepted (Phase 3)
Date: 2026-10-19

## Context

The pipeline runs in a local Airflow stack on a laptop (ADR 0005, ADR 0008). The data is only as fresh as the last time the laptop was awake with the stack up. DoltHub publishes session D at about 05:30 UTC on D+1 (see the runbook, "Prices: backfill and daily refresh"), so the freshest possible state of the project changes every morning whether or not the laptop is open, and the results page and the explorer fall behind between sessions at the keyboard.

Four constraints shape the choice.

The vendor terms allow personal analysis only, with no redistribution. No raw data goes into git (`.gitignore`, README, Data). The results page holds derived statistics only.

The explorer reads `.dbt-local/oap.duckdb` on the laptop (ADR 0011), and the DuckDB file takes one writer (ADR 0008). Whatever refreshes the data in the cloud has to hand that file to the laptop without racing a local build.

Bronze is two Iceberg tables in a SQLite-catalog warehouse (ADR 0005). The warehouse is a directory tree. The full history is about 1.8 million chain rows and 18,000 price rows, loaded from DoltHub in roughly 45 minutes of fetching (an estimate from the local backfill, not yet measured in Actions).

And the refresh must work with what a free GitHub account provides: hosted runners, a cache of up to 10 GB per repository that is evicted after 7 days without a hit, and artifacts.

## Decision

A GitHub Actions workflow, `.github/workflows/nightly.yml`, refreshes everything on a schedule, Tuesday to Saturday at 06:30 UTC, an hour after DoltHub publishes the previous session. It can also be started by hand with a date range or a full-history flag (`make nightly-run`).

The job does five things in order.

1. It restores the Iceberg warehouse (`.iceberg-local/`) from the Actions cache. The key is new on every run (`iceberg-<run id>-<attempt>`) and the restore falls back to the newest cache whose key starts with `iceberg-`.
2. It runs `scripts/refresh_bronze.py`. With a restored warehouse it fetches the last 10 sessions from DoltHub for both bronze tables; without one, or when asked, it fetches the whole history from 2020-01-01. The script writes only through `merge_into_slices` (ADR 0003): a fetched underlying replaces its own rows of a day, absence is not deletion, and an unchanged slice is not written. The step prints which path it took.
3. It saves the warehouse to the cache straight after the refresh succeeds, before any dbt step, so a failed build keeps the refreshed bronze. A failed refresh does not save, so a half-loaded full history is never restored as if it were complete.
4. It runs `make dbt-build-local` (silver, gold and the seven analytics models with their tests) and `make report`. These are the targets a developer runs, on a DuckDB file that starts empty on the runner.
5. It uploads `.dbt-local/oap.duckdb` as the artifact `gold-duckdb` and the report as `results`, both kept 14 days, and commits `docs/results.md`, the two generated figures and `README.md` back to `main` if they changed. No other path is ever committed.

The laptop takes the gold file with `make pull-gold`, which downloads the `gold-duckdb` artifact of the latest successful run with `gh`, keeps the old file as `oap.duckdb.bak` and replaces it. The explorer is unchanged: it still reads the file read-only.

The local Airflow stack stays the reference pipeline. The cloud job is a second path to the same tables and the same gold schema, built from the same code (`oap.ingest`, the dbt project, `scripts/make_report.py`). It does not replace the DAGs, and it has no Airflow dependency.

## Consequences

Good:

- The data, the results page and the explorer's input refresh every trading night with the laptop closed.
- Nothing vendor-derived enters git. The warehouse sits in a cache and the DuckDB file in an artifact; the only committed output is the results page, which holds derived statistics and a few derived spread rows, the same stance as before.
- A cold cache is not an outage. The next run notices that nothing was restored and rebuilds the history. Because every write is a slice merge, an interrupted or repeated run converges.
- The ingest logic is a plain script with tests (`tests/scripts/test_refresh_bronze.py`) over a mocked DoltHub and a temporary catalog, and it can be run by hand against any catalog.

Costs and risks:

- **Artifacts of a public repository are downloadable by anyone with read access.** The `gold-duckdb` file holds per-contract quotes derived from the vendor feed, and the vendor terms do not allow redistribution. That is why retention is 14 days rather than the default, why the README states the personal-analysis terms, and why the artifact is a build output, never a release asset. If the repository is public, anyone can fetch the file while it exists. Making the repository private removes that exposure.
- The cache is evicted after 7 days with no run (a holiday week, a disabled workflow, a repository that GitHub marks inactive after 60 days without activity). The next run then rebuilds the history, about 45 minutes by estimate, well inside the 180-minute timeout. Each night saves a new cache entry, and the 10 GB limit evicts the oldest ones.
- A restored warehouse records absolute file paths, and a hosted runner checks the repository out to the same directory every night, so they stay valid. A different runner layout would need `OAP_ICEBERG_WAREHOUSE` set explicitly.
- The cloud and local pipelines can differ by up to a day. Each fetches from DoltHub on its own schedule and each stamps `ingested_at` with its own write time. After `make pull-gold`, a local `dbt build` of the incremental model over a laptop warehouse that is older than the cloud's compares stamps from two sources; rebuild it with `--full-refresh` or pull again (runbook).
- A push made with the default `GITHUB_TOKEN` does not start the `ci` workflow, so the committed results page is not checked by CI unless a personal access token is stored as the secret `NIGHTLY_PUSH_TOKEN`. If `main` is protected, the pushing identity needs permission to push to it.
- The scheduled run is unattended. A DoltHub outage fails the run (the script exits 1 after writing what arrived), and the failure shows in the Actions tab and in GitHub's email. The next night's 10-session lookback closes the gap.
- Gold is built on a runner with 4 GB of DuckDB memory and 2 threads, not on the laptop. The build has not yet run in Actions; the first run is the measurement.

## Alternatives considered

**Commit the data.** Rejected. The vendor licence allows personal analysis only and forbids redistribution, and a public git history cannot be recalled. It would also bloat the repository with binary files that change every night.

**A scheduled Claude task that refreshes the data.** Rejected. It would give a model write access to the warehouse and an interpretive role in a deterministic job, and its runs are not visible as a build log. A workflow with a pinned toolchain and a tested script does the same work, repeatably, and is the standard shape for this job.

**A self-hosted runner on the laptop.** Rejected. It brings back the original problem, since the laptop must be awake and online at 06:30 UTC, and it gives a public repository's workflows a path to run code on a personal machine. It would also contend with the local Airflow stack for the DuckDB writer lock.

**Use the cloud targets that are already configured (S3, Glue, Snowflake).** Rejected for now. They are configured, not provisioned, and a nightly run would need a bill and credentials stored in the repository. The workflow's catalog comes from `catalog_from_env`, so pointing it at Glue later changes the environment, not the script.

**Run the local Airflow stack in Actions.** Rejected. It needs Docker, Postgres and a scheduler to run a one-shot job, and the Datasets, timetables and pools exist to coordinate a long-lived stack.
