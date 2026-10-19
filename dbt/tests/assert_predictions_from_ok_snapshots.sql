{{ config(enabled=target.type == 'duckdb', tags=['analytics']) }}
-- Only snapshots with status ok may produce predictions. Returns the predictions whose snapshot is missing
-- or was excluded.
select distinct p.underlying, p.trade_date, p.expiration, s.status
from {{ ref('calibration_prediction') }} as p
left join {{ ref('calibration_snapshot') }} as s
    on s.underlying = p.underlying and s.trade_date = p.trade_date and s.expiration = p.expiration
where s.status is null or s.status <> 'ok'
