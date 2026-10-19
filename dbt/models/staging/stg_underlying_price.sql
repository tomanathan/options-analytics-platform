with source as (select * from {{ source('bronze', 'underlying_price') }})
select trade_date, upper(trim(underlying)) as underlying, open as open_price, high as high_price,
    low as low_price, close as close_price, volume, source, ingested_at as bronze_ingested_at
from source where close > 0
