with prices as (
    select p.underlying, p.trade_date, p.open_price, p.high_price, p.low_price, p.close_price, p.volume, p.source,
        lag(p.close_price) over (partition by p.underlying order by p.trade_date) as prev_close_price
    from {{ ref('stg_underlying_price') }} as p
    inner join {{ ref('stg_watchlist') }} as w on w.symbol = p.underlying
)
select {{ dbt_utils.generate_surrogate_key(['underlying', 'trade_date']) }} as underlying_daily_key,
    {{ dbt_utils.generate_surrogate_key(['underlying']) }} as underlying_key,
    underlying, trade_date, open_price, high_price, low_price, close_price, volume, prev_close_price,
    close_price / prev_close_price - 1 as simple_return, ln(close_price / prev_close_price) as log_return, source
from prices
