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
