-- Incremental drift gate: per trade date the gold fact must hold exactly the rows of the silver view.
-- A mismatch means a deleted or rewritten bronze slice the watermark did not see; run dbt_build with full_refresh.
with silver as (
    select trade_date, count(*) as silver_rows from {{ ref('int_option_quotes') }} group by trade_date
),
gold as (
    select trade_date, count(*) as gold_rows from {{ ref('fct_option_quote') }} group by trade_date
)
select coalesce(silver.trade_date, gold.trade_date) as trade_date, silver.silver_rows, gold.gold_rows
from silver
full outer join gold on silver.trade_date = gold.trade_date
where coalesce(silver.silver_rows, 0) != coalesce(gold.gold_rows, 0)
