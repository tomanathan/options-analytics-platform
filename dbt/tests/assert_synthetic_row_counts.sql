{{ config(enabled=env_var('OAP_DBT_SOURCE', 'auto') == 'synthetic') }}
-- Row counts of every model built from the synthetic bronze catalog (scripts/make_synthetic_bronze.py):
-- 1260 DoltHub + 120 Alpaca chain rows, 38 prices (TSLA 2024-01-19 has none), 60 Alpaca rows that
-- duplicate a DoltHub contract-day, and 8 settled (underlying, expiration) pairs. Returns the mismatches.
with expected as (
    select 'stg_option_chain' as model, 1380 as expected_rows
    union all select 'stg_underlying_price', 38
    union all select 'int_option_quotes', 1320
    union all select 'int_chain_snapshots', 132
    union all select 'fct_option_quote', 1320
    union all select 'dim_contract', 120
    union all select 'fct_underlying_daily', 38
    union all select 'fct_expiration_outcome', 8
),
actual as (
    select 'stg_option_chain' as model, count(*) as actual_rows from {{ ref('stg_option_chain') }}
    union all select 'stg_underlying_price', count(*) from {{ ref('stg_underlying_price') }}
    union all select 'int_option_quotes', count(*) from {{ ref('int_option_quotes') }}
    union all select 'int_chain_snapshots', count(*) from {{ ref('int_chain_snapshots') }}
    union all select 'fct_option_quote', count(*) from {{ ref('fct_option_quote') }}
    union all select 'dim_contract', count(*) from {{ ref('dim_contract') }}
    union all select 'fct_underlying_daily', count(*) from {{ ref('fct_underlying_daily') }}
    union all select 'fct_expiration_outcome', count(*) from {{ ref('fct_expiration_outcome') }}
)
select expected.model, expected.expected_rows, actual.actual_rows
from expected
full outer join actual on expected.model = actual.model
where coalesce(actual.actual_rows, -1) != coalesce(expected.expected_rows, -1)
