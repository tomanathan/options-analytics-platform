"""Great Expectations gate for a bronze batch, before it is promoted to silver.

The gate checks what pandera's write-time contract cannot see on its own: whether a day's
volume of rows per underlying is plausible against recent history. It also repeats the core
row checks (non-null symbol, positive strike, known right, unique key) so a batch read back
from Iceberg is checked by the same suite that reports to Great Expectations.

Expectations, each identified by a stable name returned on failure:

* ``occ_symbol_not_null``: ``occ_symbol`` has no nulls.
* ``strike_positive``: ``strike`` is strictly greater than 0 dollars.
* ``right_in_set``: ``right`` is ``C`` or ``P``.
* ``key_unique``: ``(occ_symbol, trade_date, source)`` is unique.
* ``row_count:<SYMBOL>``: the rows for that underlying lie within its bounds, one
  expectation per bounded underlying, restricted to that underlying's rows with a
  ``row_condition`` (a Great Expectations ``Column("underlying") == symbol`` condition).

Row-count bounds come from history (``row_count_bounds``): the median daily row count per
underlying over a trailing window, widened by a band. An underlying with fewer than
``MIN_HISTORY_DAYS`` days of history has no bounds and is not row-count checked.

``row_count_bounds`` is pure. ``validate_bronze`` runs an ephemeral (in-memory) Great
Expectations context with a pandas datasource, analytics and progress bars switched off in
the context config; it writes nothing to disk.
"""

import math
from collections.abc import Mapping

import great_expectations as gx
import pandas as pd
from great_expectations.core.expectation_suite import ExpectationSuite
from great_expectations.data_context.types.base import (
    DataContextConfig,
    InMemoryStoreBackendDefaults,
    ProgressBarsConfig,
)
from great_expectations.expectations.core.expect_column_values_to_be_between import (
    ExpectColumnValuesToBeBetween,
)
from great_expectations.expectations.core.expect_column_values_to_be_in_set import (
    ExpectColumnValuesToBeInSet,
)
from great_expectations.expectations.core.expect_column_values_to_not_be_null import (
    ExpectColumnValuesToNotBeNull,
)
from great_expectations.expectations.core.expect_compound_columns_to_be_unique import (
    ExpectCompoundColumnsToBeUnique,
)
from great_expectations.expectations.core.expect_table_row_count_to_be_between import (
    ExpectTableRowCountToBeBetween,
)
from great_expectations.expectations.expectation import Expectation
from great_expectations.expectations.row_conditions import Column

from oap.ingest.schema import KEY_COLUMNS, RIGHTS

MIN_HISTORY_DAYS = 5
"""Days of history an underlying needs before it gets row-count bounds."""

CHECK_OCC_SYMBOL_NOT_NULL = "occ_symbol_not_null"
CHECK_STRIKE_POSITIVE = "strike_positive"
CHECK_RIGHT_IN_SET = "right_in_set"
CHECK_KEY_UNIQUE = "key_unique"
ROW_COUNT_CHECK_PREFIX = "row_count:"
SUITE_NAME = "bronze_option_chain"


def _context_config() -> DataContextConfig:
    """In-memory context config with analytics and progress bars switched off."""
    return DataContextConfig(
        store_backend_defaults=InMemoryStoreBackendDefaults(),
        analytics_enabled=False,
        progress_bars=ProgressBarsConfig(globally=False, metric_calculations=False),
    )


class BronzeQualityError(Exception):
    """A bronze batch failed the gate.

    Args:
        failed: Names of the failed expectations, as returned by ``validate_bronze``.
    """

    failed: list[str]

    def __init__(self, failed: list[str]) -> None:
        """Record the failed expectation names and build a message listing them."""
        self.failed = list(failed)
        super().__init__(f"bronze quality gate failed: {', '.join(self.failed)}")


def row_count_check_name(underlying: str) -> str:
    """Return the expectation name of an underlying's row-count check.

    Args:
        underlying: Underlying ticker, for example ``"SPY"``.

    Returns:
        ``"row_count:SPY"`` for ``"SPY"``.
    """
    return f"{ROW_COUNT_CHECK_PREFIX}{underlying}"


def row_count_bounds(
    history: pd.DataFrame, *, window_days: int = 20, band: float = 0.5
) -> dict[str, tuple[int, int]]:
    """Derive plausible daily row-count bounds per underlying from bronze history.

    For each underlying: count rows per ``trade_date``, keep the most recent ``window_days``
    trade dates that underlying has, take the median count ``m``, and return
    ``(floor(m * (1 - band)), ceil(m * (1 + band)))``. Underlyings with fewer than
    ``MIN_HISTORY_DAYS`` dates in the window are left out.

    Args:
        history: Bronze rows with at least ``underlying`` and ``trade_date`` columns, usually
            one source over recent sessions.
        window_days: Number of most recent trade dates per underlying to use.
        band: Relative half-width of the bounds, as a decimal (0.5 means plus or minus 50%).

    Returns:
        Underlying to ``(min_rows, max_rows)``, both inclusive.

    Raises:
        ValueError: If ``window_days`` is not positive or ``band`` is not in ``[0, 1]``.
    """
    if window_days <= 0:
        raise ValueError(f"window_days must be positive, got {window_days}")
    if not 0 <= band <= 1:
        raise ValueError(f"band must be in [0, 1], got {band}")
    bounds: dict[str, tuple[int, int]] = {}
    if history.empty:
        return bounds
    daily = history.groupby(["underlying", "trade_date"], observed=True).size()
    for underlying, counts in daily.groupby(level="underlying", observed=True):
        recent = counts.sort_index(level="trade_date").tail(window_days)
        if len(recent) < MIN_HISTORY_DAYS:
            continue
        median = float(recent.median())
        bounds[str(underlying)] = (
            math.floor(median * (1 - band)),
            math.ceil(median * (1 + band)),
        )
    return bounds


def build_suite(bounds: Mapping[str, tuple[int, int]]) -> ExpectationSuite:
    """Build the bronze expectation suite.

    Contains the four row expectations and one ``ExpectTableRowCountToBeBetween`` per entry
    of ``bounds``, restricted to that underlying with
    ``row_condition=Column("underlying") == symbol`` (GX 1.9+ condition objects; the string
    form with ``condition_parser`` is deprecated). Each expectation carries its name (see the
    module docstring) in ``meta["name"]``. The suite is built without a data context.

    Args:
        bounds: Underlying to ``(min_rows, max_rows)``, as from ``row_count_bounds``.

    Returns:
        A suite named ``bronze_option_chain``, not attached to any data context.
    """
    expectations: list[Expectation] = [
        ExpectColumnValuesToNotBeNull(
            column="occ_symbol", meta={"name": CHECK_OCC_SYMBOL_NOT_NULL}
        ),
        ExpectColumnValuesToBeBetween(
            column="strike", min_value=0, strict_min=True, meta={"name": CHECK_STRIKE_POSITIVE}
        ),
        ExpectColumnValuesToBeInSet(
            column="right", value_set=sorted(RIGHTS), meta={"name": CHECK_RIGHT_IN_SET}
        ),
        ExpectCompoundColumnsToBeUnique(
            column_list=list(KEY_COLUMNS), meta={"name": CHECK_KEY_UNIQUE}
        ),
    ]
    for underlying, (low, high) in sorted(bounds.items()):
        expectations.append(
            ExpectTableRowCountToBeBetween(
                min_value=low,
                max_value=high,
                row_condition=Column("underlying") == underlying,
                meta={"name": row_count_check_name(underlying)},
            )
        )
    return ExpectationSuite(name=SUITE_NAME, expectations=expectations)


def validate_bronze(frame: pd.DataFrame, bounds: Mapping[str, tuple[int, int]]) -> list[str]:
    """Validate a bronze batch and return the names of the failed expectations.

    Args:
        frame: The batch, with at least BRONZE_SCHEMA's ``underlying``, ``occ_symbol``,
            ``trade_date``, ``strike``, ``right`` and ``source`` columns.
        bounds: Row-count bounds per underlying.

    Returns:
        Failed expectation names, sorted; empty when the batch passes. An expectation that
        raised while evaluating counts as failed.
    """
    context = gx.get_context(mode="ephemeral", project_config=_context_config())
    batch_definition = (
        context.data_sources.add_pandas(name="bronze")
        .add_dataframe_asset(name="option_chain")
        .add_batch_definition_whole_dataframe(name="batch")
    )
    batch = batch_definition.get_batch(batch_parameters={"dataframe": frame})
    result = batch.validate(build_suite(bounds))
    failed = {
        str((r.expectation_config.meta or {}).get("name", r.expectation_config.type))
        for r in result.results
        if not r.success and r.expectation_config is not None
    }
    return sorted(failed)


def assert_bronze_ok(frame: pd.DataFrame, history: pd.DataFrame) -> None:
    """Gate a bronze batch against bounds derived from its history.

    Args:
        frame: The batch to promote.
        history: Recent bronze rows to derive row-count bounds from (``row_count_bounds``
            with its defaults).

    Raises:
        BronzeQualityError: If any expectation fails; ``failed`` lists them.
    """
    failed = validate_bronze(frame, row_count_bounds(history))
    if failed:
        raise BronzeQualityError(failed)
