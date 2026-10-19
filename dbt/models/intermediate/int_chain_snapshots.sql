{{ config(materialized='table') }}
select {{ dbt_utils.generate_surrogate_key(['underlying', 'trade_date', 'expiration']) }} as chain_snapshot_key,
    underlying, trade_date, expiration, min(dte_days) as dte_days,
    count(distinct strike) as n_strikes,
    sum(case when option_right = 'P' then 1 else 0 end) as n_puts,
    sum(case when option_right = 'C' then 1 else 0 end) as n_calls,
    min(strike) as min_strike, max(strike) as max_strike, max(underlying_close) as underlying_close
from {{ ref('int_option_quotes') }} group by underlying, trade_date, expiration
