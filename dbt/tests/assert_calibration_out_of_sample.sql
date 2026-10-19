{{ config(enabled=target.type == 'duckdb', tags=['analytics']) }}
-- Leakage gate. A fold map must be fitted only on predictions whose expiration is before 1 January of the fold
-- year, and so before the first trade date it is applied to. Returns the maps that break either rule.
with maps as (
    select distinct map_id, fold, train_max_expiration
    from {{ ref('calibration_map') }}
    where fold is not null
),
applied as (
    select map_id, min(trade_date) as first_trade_date
    from {{ ref('calibration_sample') }}
    group by map_id
)
select maps.map_id, maps.fold, maps.train_max_expiration, applied.first_trade_date
from maps
inner join applied on applied.map_id = maps.map_id
where maps.train_max_expiration >= applied.first_trade_date
    or maps.train_max_expiration >= cast(cast(maps.fold as varchar) || '-01-01' as date)
