-- Incremental drift gate: per trade date the gold fact must match the silver view in row count and in
-- the underlying_close column (a checksum of the closes, and how many are non-null). A mismatch means a
-- deleted or rewritten bronze slice, or a late or corrected price, that the watermark did not see; run
-- dbt_build with full_refresh. Closes are dollars; the checksum is rounded to cents and compared with a
-- half-cent tolerance so summation order cannot fail it.
with silver as (
    select trade_date,
        count(*) as silver_rows,
        count(underlying_close) as silver_closes,
        round(sum(coalesce(cast(underlying_close as double precision), -1)), 2) as silver_close_sum
    from {{ ref('int_option_quotes') }}
    group by trade_date
),
gold as (
    select trade_date,
        count(*) as gold_rows,
        count(underlying_close) as gold_closes,
        round(sum(coalesce(cast(underlying_close as double precision), -1)), 2) as gold_close_sum
    from {{ ref('fct_option_quote') }}
    group by trade_date
)
select coalesce(silver.trade_date, gold.trade_date) as trade_date,
    silver.silver_rows, gold.gold_rows,
    silver.silver_closes, gold.gold_closes,
    silver.silver_close_sum, gold.gold_close_sum
from silver
full outer join gold on silver.trade_date = gold.trade_date
where coalesce(silver.silver_rows, 0) != coalesce(gold.gold_rows, 0)
    or coalesce(silver.silver_closes, 0) != coalesce(gold.gold_closes, 0)
    or abs(coalesce(silver.silver_close_sum, 0) - coalesce(gold.gold_close_sum, 0)) > 0.005
