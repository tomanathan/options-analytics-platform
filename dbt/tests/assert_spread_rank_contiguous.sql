{{ config(enabled=target.type == 'duckdb', tags=['analytics']) }}
-- Ranks run 1..k over the eligible spreads and nowhere else: as many ranks as the highest rank, and a rank
-- exactly when the spread is eligible. Returns one row when the table breaks that.
with summary as (
    select count("rank") as n_ranked, coalesce(max("rank"), 0) as max_rank,
        sum(case when eligible and "rank" is null then 1 when not eligible and "rank" is not null then 1 else 0 end)
            as n_mismatched
    from {{ ref('spread_scores') }}
)
select n_ranked, max_rank, n_mismatched
from summary
where n_ranked <> max_rank or n_mismatched > 0
