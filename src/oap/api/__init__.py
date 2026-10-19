"""Explorer API: a read-only FastAPI service over the gold tables of the DuckDB file.

The service serves the risk-neutral distributions, the calibrated probability heatmaps and
the scored put credit spreads that ``dbt build`` leaves in the ``gold`` schema. It opens the
database read-only, briefly and rarely, and answers from memory, so it never holds the
writer lock that ``dbt_build`` and ``score_spreads`` need (docs/design/explorer-v1.md).

Units: strikes, prices, credits and closes are in dollars per share ($/sh); volatility is a
decimal (0.20, not 20%); probabilities and returns are decimals in the data; time is in
calendar days or in years (ACT/365).
"""
