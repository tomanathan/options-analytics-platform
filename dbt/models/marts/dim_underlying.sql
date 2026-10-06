select
    {{ dbt_utils.generate_surrogate_key(['symbol']) }} as underlying_key,
    symbol,
    sector,
    added_on
from {{ ref('stg_watchlist') }}
