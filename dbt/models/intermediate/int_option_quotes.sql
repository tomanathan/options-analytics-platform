with chain as (
    select *, max(bronze_ingested_at) over (partition by trade_date) as chain_ingested_at
    from {{ ref('stg_option_chain') }}
),
price_stamps as (
    select trade_date, max(bronze_ingested_at) as price_ingested_at
    from {{ ref('stg_underlying_price') }}
    group by trade_date
),
deduplicated as (
    select * from chain
    qualify row_number() over (partition by occ_symbol, trade_date order by
        case source when 'dolthub' then 1 when 'alpaca_indicative' then 2 else 3 end,
        bronze_ingested_at desc) = 1
),
priced as (
    select q.*,
        coalesce(p.close_price, q.source_underlying_price) as underlying_close,
        case when p.close_price is not null then 'stocks'
             when q.source_underlying_price is not null then 'chain' end as underlying_close_source,
        {{ dbt.datediff('q.trade_date', 'q.expiration', 'day') }} as dte_days,
        case when q.bid is not null and q.ask is not null then (q.bid + q.ask) / 2 end as mid,
        -- The watermark moves when either the chain or the prices of the date are (re)written; a
        -- date without a price row keeps the chain stamp.
        greatest(q.chain_ingested_at, coalesce(s.price_ingested_at, q.chain_ingested_at))
            as trade_date_ingested_at
    from deduplicated as q
    left join {{ ref('stg_underlying_price') }} as p
        on p.underlying = q.underlying and p.trade_date = q.trade_date
    left join price_stamps as s on s.trade_date = q.trade_date
)
select occ_symbol, trade_date, underlying, expiration, strike, option_right, bid, ask, mid,
    ask - bid as spread, case when mid > 0 then (ask - bid) / mid end as spread_pct,
    last_price, volume, open_interest, source_iv, source_delta, source_gamma, source_theta,
    source_vega, source_rho, underlying_close, underlying_close_source,
    cast(strike as double precision) / underlying_close as moneyness,
    dte_days, cast(dte_days as double precision) / 365 as dte_years,
    source, bronze_ingested_at, trade_date_ingested_at
from priced
