{{ config(enabled=target.type == 'duckdb', tags=['analytics']) }}
-- Ranks run 1..k over the eligible spreads and nowhere else: as many ranks as the highest rank, and a rank
-- exactly when the spread is eligible. The alternative ranks (rank_edge, rank_rr, rank_entry) are each 1..k
-- over a subset of the eligible spreads: contiguous, never set on an ineligible spread, rank_edge and rank_rr
-- set together, and rank_entry only where rank_edge is set. Returns one row when the table breaks that.
with summary as (
    select count("rank") as n_ranked, coalesce(max("rank"), 0) as max_rank,
        sum(case when eligible and "rank" is null then 1 when not eligible and "rank" is not null then 1 else 0 end)
            as n_mismatched
    from {{ ref('spread_scores') }}
),
alternatives as (
    select
        count(rank_edge) as n_edge, coalesce(max(rank_edge), 0) as max_edge,
        count(rank_rr) as n_rr, coalesce(max(rank_rr), 0) as max_rr,
        count(rank_entry) as n_entry, coalesce(max(rank_entry), 0) as max_entry,
        sum(case when (rank_edge is null) <> (rank_rr is null) then 1 else 0 end) as n_pair_mismatched,
        sum(case when (rank_edge is not null or rank_rr is not null or rank_entry is not null) and not eligible
            then 1 else 0 end) as n_ineligible_ranked,
        sum(case when rank_entry is not null and rank_edge is null then 1 else 0 end) as n_entry_outside_guards
    from {{ ref('spread_scores') }}
)
select n_ranked, max_rank, n_mismatched, n_edge, max_edge, n_rr, max_rr, n_entry, max_entry,
    n_pair_mismatched, n_ineligible_ranked, n_entry_outside_guards
from summary
cross join alternatives
where n_ranked <> max_rank or n_mismatched > 0
    or n_edge <> max_edge or n_rr <> max_rr or n_entry <> max_entry
    or n_pair_mismatched > 0 or n_ineligible_ranked > 0 or n_entry_outside_guards > 0
