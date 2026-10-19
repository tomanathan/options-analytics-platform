{{ config(materialized='incremental', incremental_strategy='delete+insert', unique_key='trade_date', on_schema_change='fail') }}
select {{ dbt_utils.generate_surrogate_key(['occ_symbol', 'trade_date']) }} as option_quote_key,
    {{ dbt_utils.generate_surrogate_key(['occ_symbol']) }} as contract_key,
    {{ dbt_utils.generate_surrogate_key(['underlying']) }} as underlying_key,
    occ_symbol, trade_date, underlying, expiration, strike, option_right, bid, ask, mid, spread,
    spread_pct, last_price, volume, open_interest, source_iv, source_delta, source_gamma,
    source_theta, source_vega, source_rho, underlying_close, underlying_close_source, moneyness,
    dte_days, dte_years, source, trade_date_ingested_at
from {{ ref('int_option_quotes') }}
{% if is_incremental() %}
where trade_date_ingested_at > (select max(trade_date_ingested_at) from {{ this }})
   or not exists (select 1 from {{ this }})
{% endif %}
