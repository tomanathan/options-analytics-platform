"""Pure options math for the put credit spread engine.

Everything in this package is a side-effect-free function of its arguments: no I/O, no
clocks, no global state. Callers load data elsewhere and pass plain values in.

Units are fixed across the package:

* Prices, strikes, credits and losses are in US dollars per share.
* Volatility is a decimal (0.20 means 20%).
* Time is in years (30 calendar days is 30 / 365).
* Interest rates are decimal annual percentage yields (0.036 means 3.6% APY).
* Probabilities are decimals in [0, 1].
"""
