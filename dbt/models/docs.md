{% docs stg_watchlist %}
The watchlist seed, cleaned. One row per tracked underlying with its ticker trimmed and
upper-cased so it joins reliably to vendor data. This is the list of symbols whose daily
options chains the platform ingests.
{% enddocs %}

{% docs dim_underlying %}
Underlying dimension. One row per tracked symbol, keyed by a surrogate hash of the
symbol so fact tables (chains, spreads, outcomes) join on a stable key that does not
change if a ticker's attributes change.
{% enddocs %}

{% docs stg_option_chain %}
Bronze option chain, renamed and filtered. Grain: one row per contract (`occ_symbol`) per
`trade_date` per `source`, so a day that both DoltHub and Alpaca covered has two rows here.
Rows with a non-positive strike, an expiration before the trade date or a crossed quote
(bid above ask) are dropped; the bronze Great Expectations suite is the first gate for those
and this filter keeps a bad vendor row out of silver. The reserved word `right` becomes
`option_right`; vendor greeks and implied volatility keep a `source_` prefix because they are
the vendor's values as ADR 0004 keeps them, not the platform's. Prices are dollars per share, volatility
is a decimal (0.20 is 20%).
{% enddocs %}

{% docs stg_underlying_price %}
Bronze daily underlying bars, renamed. Grain: one row per `underlying` per `trade_date`. The
unique-combination test excludes `source`, so it fails closed if a second price source ever
lands; a rule for choosing between sources would be needed first. Rows with a non-positive
close are dropped. Prices are dollars per share as traded, **not adjusted for splits**: an
AAPL close before its 2020 4-for-1 split is four times the close after it.
{% enddocs %}

{% docs int_option_quotes %}
One quote per contract per trade date, enriched. Grain: `occ_symbol` x `trade_date`. Where
DoltHub and Alpaca both cover a contract-day, DoltHub wins, then the later write;
`source` records which vendor's values survived and every `source_*` column is that vendor's
value. `underlying_close` prefers the official close from `stg_underlying_price` and falls
back to the chain vendor's underlying price only when no stocks row exists for the day (for
example today's Alpaca snapshot before prices land); `underlying_close_source` says which
(`stocks` or `chain`). Every contract of a day therefore sees the same close, and it is the
series `fct_expiration_outcome` settles on. `dte_years` is calendar days divided by 365,
`moneyness` is strike over close, `spread_pct` is spread over mid (at most 2.0). A view: it
always matches the Iceberg snapshot pinned at the start of the dbt run.
{% enddocs %}

{% docs int_chain_snapshots %}
One row per underlying, trade date and expiration: how many strikes, puts and calls the chain
lists and the strike range. Grain: `underlying` x `trade_date` x `expiration`. The singular
test `assert_close_within_strike_range` reads it to catch a close that cannot belong to that
day's strikes, such as a split-adjusted close against unadjusted strikes.
{% enddocs %}

{% docs fct_option_quote %}
The engine's input: one quote per contract per trade date. Grain: `occ_symbol` x `trade_date`,
the columns of `int_option_quotes` plus surrogate keys to `dim_contract` and `dim_underlying`.
Incremental with `delete+insert` on `trade_date`: a run rebuilds every trade date whose
`trade_date_ingested_at` (the latest bronze write across all sources of the date) is newer than
the newest one already loaded, which mirrors the partition-replace writes of ADR 0003, so a
corrected backfill slice is reprocessed. A bronze slice that is deleted outright is not seen by
that watermark; `assert_fct_option_quote_matches_silver` compares per-date row counts with the
silver view and fails on drift, and a `full_refresh` run of the `dbt_build` DAG rebuilds the
table. Prices are dollars per share, `dte_years` is calendar days over 365, volatility is a
decimal.
{% enddocs %}

{% docs dim_contract %}
Contract dimension. Grain: one row per `occ_symbol`, with the underlying, expiration, strike
and right that the symbol encodes, the first and last trade date it was quoted and the number
of quote days. Built from `int_option_quotes`, so a symbol whose attributes disagreed between
rows would fail the uniqueness tests instead of being silently collapsed.
{% enddocs %}

{% docs fct_underlying_daily %}
Daily bars of the watchlist underlyings with returns. Grain: `underlying` x `trade_date`.
Prices are dollars per share as traded and **unadjusted for splits or dividends**, because the
option strikes on the same date are quoted against the unadjusted price. `simple_return` and
`log_return` are therefore wrong across a split day; the warn-level range test on `log_return`
flags those days. Returns use the previous session present for that underlying, so a gap in
the bronze history produces a multi-day return.
{% enddocs %}

{% docs fct_expiration_outcome %}
The settlement price of every expiration seen in the chains, for calibrating the market-implied
distribution. Grain: `underlying` x `expiration`. A session is any date with a price for any
underlying; an expiration that falls on a holiday or weekend settles on the last session within
4 days before it (`settlement_lag_days`). Only expirations on or before the latest session
are included, and an underlying with no price on its settlement session is absent from the
table rather than carried with a null close. `settlement_close` is the as-traded close in
dollars from `fct_underlying_daily`.
{% enddocs %}
