select {{ dbt_utils.generate_surrogate_key(['occ_symbol']) }} as contract_key,
    {{ dbt_utils.generate_surrogate_key(['underlying']) }} as underlying_key,
    occ_symbol, underlying, expiration, strike, option_right,
    min(trade_date) as first_seen, max(trade_date) as last_seen, count(*) as n_quote_days
from {{ ref('int_option_quotes') }} group by occ_symbol, underlying, expiration, strike, option_right
