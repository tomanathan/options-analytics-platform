"""Market-implied distribution of the underlying price at expiry.

Phase 3 will implement this module. It will extract the risk-neutral cumulative
distribution function of the underlying price at expiry from vertical spread prices, using
the Breeden-Litzenberger result: the price of a vertical spread divided by its width
approximates the risk-neutral probability mass beyond its strikes, and in the limit of
narrow butterflies the second derivative of option price with respect to strike gives the
density.

Inputs will be strikes in dollars, mid prices in dollars per share for the options at
those strikes, and time to expiry in years. The output will be a monotone CDF over price
in dollars, with probabilities as decimals in [0, 1]. Calibration of this risk-neutral
distribution against realized outcomes since 2019 happens downstream of this module.
"""
