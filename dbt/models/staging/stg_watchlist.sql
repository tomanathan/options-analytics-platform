select
    upper(trim(symbol)) as symbol,
    sector,
    added_on
from {{ ref('watchlist') }}
