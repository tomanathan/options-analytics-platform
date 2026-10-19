# 0007. Store underlying prices as traded, not adjusted

Status: Accepted (Phase 2)
Date: 2026-10-19

## Context

The engine needs the closing price of each underlying for two jobs. It needs the price on the quote date to place strikes (moneyness). It needs the price on the expiration date to decide whether a spread expired profitable, which is the outcome the calibration compares predictions with. The DoltHub option chains carry no underlying price, and the Alpaca snapshot carries one only for the day it was taken, so the history needs a separate source.

DoltHub's `post-no-preference/stocks` database has free daily OHLCV from the same API the chain client already uses. Its `ohlcv` table holds prices as traded on each date. A second table, `split`, holds the split ratios.

Option strikes are quoted against the price as traded. AAPL closed at 499.23 on 2020-08-28 and at 129.04 on 2020-08-31, across its 4-for-1 split, and the strikes listed on each date sit around the price of that date. A split-adjusted close for 2020-08-28 (about 124.81) would fall far below the strikes of that day's chain.

## Decision

`bronze.underlying_price` stores the DoltHub bars as received: open, high, low and close in dollars per share as traded, volume in shares, `source = dolthub_stocks`, one row per `(underlying, trade_date, source)`. Prices are not adjusted for splits or dividends in bronze, in silver or in `fct_underlying_daily`, and the `split` table is not loaded or applied. The table is a second `TableSpec` and follows the same overwrite rule as the option chain (ADR 0003).

Three things follow in the code:

- **The contract does not constrain `open`.** The frame schema requires `close > 0`, `volume >= 0`, `high >= low` and `low <= close <= high` where present. It does not check `open`, because the vendor holds a row where it is out of range (IWM on 2021-05-05 opened at 224.28 against a high of 224.16) and rejecting it would fail the whole month's write. The parser logs a warning instead.
- **Silver prefers the stocks close.** `int_option_quotes` sets `underlying_close` from `stg_underlying_price` when a row exists for the day and falls back to the chain vendor's price otherwise (`underlying_close_source` records which).
- **A gate checks the unit.** The singular test `assert_close_within_strike_range` fails when a day's close lies outside the strike range of that day's chain, which is what a split-adjusted close against as-traded strikes looks like.

`fct_underlying_daily` computes simple and log returns from the as-traded closes. A warn-level test flags `log_return` outside plus or minus 0.5, which marks split days. `fct_expiration_outcome` settles on the as-traded close, which is the price the strikes of that expiration were quoted against.

## Consequences

Good:

- The price and the strikes are in the same unit on every date, so moneyness and settlement need no per-date adjustment factor.
- Bronze stays as received. A new split does not rewrite history; a restated vendor table is handled by re-running the affected slices.
- The unit mismatch that would silently corrupt moneyness and outcomes fails a test before gold is built.

Costs and risks:

- Returns are wrong across split days, and dividends are ignored. Nothing in the repository applies the `split` table. Any analysis that needs a continuous return series must build one downstream, and none does today. The warn test lists the split days.
- DoltHub publishes a session at about 05:30 UTC on the next day, so the newest session has no price until the following morning. `daily_prices` runs after the close and re-fetches a trailing five-session window, so each session appears one run late. Until then `underlying_close_source` is `chain` for Alpaca rows and null for DoltHub rows.
- Before 2022-06-09, `META` in this database is a different instrument, the Roundhill Metaverse ETF, and the FB history is not loaded. In the loaded data the META chains begin on 2022-07-01, so they never meet the ETF rows, but `fct_underlying_daily` holds the ETF series under `META` until the rename. Treat META returns before 2022-06-09 as invalid.
- Prices come from one vendor. If DoltHub's bars disagree with the official close on some day, there is no second source to cross-check with; the strike-range gate catches only gross errors.

## Alternatives considered

**Split-adjust in bronze.** Rejected. Bronze is the as-received layer (ADR 0004 applies the same rule to vendor greeks). Adjusted prices would no longer match the strikes quoted on the same date, which is the comparison the engine makes. Every future split would also change the stored value of every earlier row, so history would need rewriting, and slice overwrite (ADR 0003) works per day, not per symbol across all days.

**Derive spot from put-call parity.** Rejected. Parity gives the forward, not the spot, and needs a rate and a dividend assumption; the engine already uses it for the forward when quotes allow. As the only source of the spot it would be circular, would fail on days when the near-the-money call or put has no quote, and would make settlement prices depend on quote noise.

**Alpaca stock trades.** Rejected. The endpoint returns individual prints, so a daily close would have to be derived from them with rules of our own, and it needs an API key where the DoltHub path needs none. DoltHub is already the source of the chain history, so the client, paging, month chunking and publication lag are the same.
