"""Options analytics platform (oap).

oap turns daily US equity options chains into ranked put credit spread candidates. The
``ingest`` package lands raw chains and underlying prices in Apache Iceberg (bronze) on S3,
dbt models refine them on Snowflake (silver and gold), ``quality`` holds the Great
Expectations gates between those layers, and ``engine`` holds the pure options math that
derives a market-implied distribution from vertical spread prices and scores spreads on
expected return on max loss.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
