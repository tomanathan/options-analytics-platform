with sessions as (select distinct trade_date as session_date from {{ ref('fct_underlying_daily') }}),
expirations as (
    select distinct underlying, expiration from {{ ref('dim_contract') }}
    where expiration <= (select max(session_date) from sessions)
),
settlement_sessions as (
    select e.underlying, e.expiration, s.session_date as settlement_date
    from expirations as e
    inner join sessions as s on s.session_date <= e.expiration
        and s.session_date >= {{ dbt.dateadd('day', -4, 'e.expiration') }}
    qualify row_number() over (partition by e.underlying, e.expiration order by s.session_date desc) = 1
)
select {{ dbt_utils.generate_surrogate_key(['ss.underlying', 'ss.expiration']) }} as expiration_outcome_key,
    {{ dbt_utils.generate_surrogate_key(['ss.underlying']) }} as underlying_key,
    ss.underlying, ss.expiration, ss.settlement_date,
    {{ dbt.datediff('ss.settlement_date', 'ss.expiration', 'day') }} as settlement_lag_days,
    p.close_price as settlement_close
from settlement_sessions as ss
inner join {{ ref('fct_underlying_daily') }} as p on p.underlying = ss.underlying and p.trade_date = ss.settlement_date
