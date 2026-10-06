"""Expected return on collateral for put credit spreads.

Phase 3 will implement this module. For a put credit spread (short a higher-strike put,
long a lower-strike put with the same expiry) it will compute:

* the credit received, in dollars per share;
* the maximum loss, in dollars per share, equal to the strike width in dollars minus the
  credit;
* the probability of profit, as a decimal in [0, 1], taken from the calibrated
  distribution of the underlying price at expiry;
* the cash interest earned on the collateral (the maximum loss held as cash) at a decimal
  APY, such as 0.036 for 3.6%, over the holding period in years;
* the expected return on collateral, as a decimal, combining the expected payoff of the
  spread with that interest.

Scores are comparable across underlyings, widths and expiries because every input is
normalised to dollars per share of collateral and time in years.
"""
