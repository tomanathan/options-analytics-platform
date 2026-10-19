with source as (select * from {{ source('bronze', 'option_chain') }})
select trade_date, upper(trim(underlying)) as underlying, occ_symbol, expiration,
    cast(strike as decimal(10, 3)) as strike, {{ adapter.quote('right') }} as option_right,
    bid, ask, last as last_price, volume, open_interest,
    iv as source_iv, delta as source_delta, gamma as source_gamma, theta as source_theta,
    vega as source_vega, rho as source_rho, underlying_price as source_underlying_price,
    source, ingested_at as bronze_ingested_at
from source
where strike > 0 and expiration >= trade_date and (bid is null or ask is null or bid <= ask)
