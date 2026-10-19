{{ config(enabled=target.type == 'duckdb', tags=['analytics']) }}
-- A calibration map is a monotone curve: knot positions strictly increase and the calibrated value never
-- decreases along them. Returns the knots that break either rule.
with knots as (
    select map_id, knot_index, predicted, calibrated,
        lag(predicted) over (partition by map_id order by knot_index) as previous_predicted,
        lag(calibrated) over (partition by map_id order by knot_index) as previous_calibrated
    from {{ ref('calibration_map') }}
)
select map_id, knot_index, predicted, calibrated, previous_predicted, previous_calibrated
from knots
where predicted <= previous_predicted or calibrated < previous_calibrated
