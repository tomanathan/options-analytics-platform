"""Calibration backtest and live spread scoring on top of ``oap.engine``.

The package is a pure core that dbt Python models call: ``sample`` turns option chains
and outcomes into labelled predictions, ``backtest`` fits and evaluates walk-forward
calibration maps, ``scoring`` ranks the latest session's put credit spreads, and ``io``
is the only module that touches a database relation. Prices are in dollars per share,
rates are decimal APYs, times are in years and probabilities are decimals in [0, 1].

``oap.analytics`` imports only the standard library, numpy, pandas and ``oap.engine`` so
that it can be installed into the dbt virtualenv without the ingestion dependencies.
"""
