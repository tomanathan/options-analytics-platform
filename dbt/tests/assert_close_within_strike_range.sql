-- A day's official close must lie inside the strike range the chain lists for that day. A split-adjusted
-- close against unadjusted strikes (or the reverse) falls outside it and fails the gate before gold is built.
select underlying, trade_date, max(underlying_close) as underlying_close,
    min(min_strike) as min_strike, max(max_strike) as max_strike
from {{ ref('int_chain_snapshots') }}
group by underlying, trade_date
having max(underlying_close) < min(min_strike) or max(underlying_close) > max(max_strike)
