# Test fixtures

The Alpaca JSON files in this directory are hand-built from the response shapes in Alpaca's
market data API documentation, because no Alpaca API key was available when they were
written. They are not recordings of live responses: symbols, prices and timestamps are
invented to exercise the parser and the pagination logic.

- `alpaca_snapshots_spy_page1.json`: first page of `GET /v1beta1/options/snapshots/SPY`,
  with a `next_page_token`. Holds a fully populated call and put, and a contract with only a
  `latestQuote`.
- `alpaca_snapshots_spy_page2.json`: last page (`next_page_token` is null). Holds a contract
  with only a `latestTrade` and `dailyBar`, and one with neither quote nor trade, which the
  parser must skip.
- `alpaca_latest_trades.json`: `GET /v2/stocks/trades/latest?symbols=SPY,QQQ&feed=iex`.

Bronze Parquet fixtures for the quality suite are not stored here. `tests/quality/conftest.py`
builds them from a seeded generator into a temporary directory on every run.
