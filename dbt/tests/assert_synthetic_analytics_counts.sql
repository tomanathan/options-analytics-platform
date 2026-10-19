{{ config(enabled=target.type == 'duckdb' and env_var('OAP_DBT_SOURCE', 'auto') == 'synthetic', tags=['analytics']) }}
-- Row counts of the analytics models built from the synthetic bronze catalog (scripts/make_synthetic_bronze.py:
-- SPY, AAPL and TSLA over 13 sessions, expirations 2024-01-12, 01-15, 01-19 and 02-16). Of the 132 snapshots,
-- 45 are ok (not within 7 days of expiry, and settled: 18 each for SPY and AAPL, 9 for TSLA, whose 01-19 expiry
-- has no settlement price), 39 are too short and 48 unsettled. The ok snapshots list 5 strikes, so the CDF
-- covers a narrow band and the 13-point moneyness grid yields 210 predictions. All are in 2024, so the fold_2024
-- map trains on nothing (identity, 0 samples), nothing is out of sample and the metrics and bins are empty. The
-- production map sees all 210 predictions, more than the 50 needed to fit. The latest session lists 8 spreads
-- on the 2024-02-16 expiry, all with a short strike above the close, so none is eligible or ranked.
-- Returns the mismatches.
with expected as (
    select 'calibration_snapshot' as metric, 132 as expected_value
    union all select 'snapshots_ok', 45
    union all select 'snapshots_too_short', 39
    union all select 'snapshots_unsettled', 48
    union all select 'calibration_prediction', 210
    union all select 'calibration_sample', 210
    union all select 'sample_out_of_sample', 0
    union all select 'calibration_map_ids', 2
    union all select 'calibration_map_identity_ids', 1
    union all select 'production_map_n_samples', 210
    union all select 'calibration_metrics', 0
    union all select 'calibration_bins', 0
    union all select 'spread_scores', 8
    union all select 'spread_scores_expiring_2024_02_16', 8
    union all select 'spread_scores_eligible', 0
    union all select 'spread_scores_ranked', 0
),
actual as (
    select 'calibration_snapshot' as metric, count(*) as actual_value from {{ ref('calibration_snapshot') }}
    union all select 'snapshots_ok', count(*) from {{ ref('calibration_snapshot') }} where status = 'ok'
    union all select 'snapshots_too_short', count(*) from {{ ref('calibration_snapshot') }} where status = 'too_short'
    union all select 'snapshots_unsettled', count(*) from {{ ref('calibration_snapshot') }} where status = 'unsettled'
    union all select 'calibration_prediction', count(*) from {{ ref('calibration_prediction') }}
    union all select 'calibration_sample', count(*) from {{ ref('calibration_sample') }}
    union all select 'sample_out_of_sample', count(*) from {{ ref('calibration_sample') }} where is_out_of_sample
    union all select 'calibration_map_ids', count(distinct map_id) from {{ ref('calibration_map') }}
    union all select 'calibration_map_identity_ids', count(distinct map_id) from {{ ref('calibration_map') }}
        where is_identity
    union all select 'production_map_n_samples', coalesce(max(n_samples), -1) from {{ ref('calibration_map') }}
        where map_id = 'production'
    union all select 'calibration_metrics', count(*) from {{ ref('calibration_metrics') }}
    union all select 'calibration_bins', count(*) from {{ ref('calibration_bins') }}
    union all select 'spread_scores', count(*) from {{ ref('spread_scores') }}
    union all select 'spread_scores_expiring_2024_02_16', count(*) from {{ ref('spread_scores') }}
        where expiration = cast('2024-02-16' as date)
    union all select 'spread_scores_eligible', count(*) from {{ ref('spread_scores') }} where eligible
    union all select 'spread_scores_ranked', count("rank") from {{ ref('spread_scores') }}
)
select expected.metric, expected.expected_value, actual.actual_value
from expected
full outer join actual on expected.metric = actual.metric
where coalesce(actual.actual_value, -1) != coalesce(expected.expected_value, -2)
