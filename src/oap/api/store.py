"""The only place the database is read: thread-safe caches in front of ``GoldReader``.

One ``threading.RLock`` guards every cache, and database reads happen under it too, so at
most one read-only connection is ever open. Entries are keyed by the file signature, so a
dbt write (which changes the signature) invalidates them. After the first load of an
underlying, scrubbing through sessions touches memory only.

Lock handling: when the signature changed and the file cannot be opened because a writer
holds the lock, the store answers from the entries of the last good signature and says so
(``Served.stale``). Without such an entry the ``DatabaseBusy`` error reaches the caller,
which answers 503 with ``Retry-After``.

Units: those of the gold tables; see ``oap.api.models``.
"""

from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import RLock
from typing import Any, Final, Literal

import pandas as pd

from oap.analytics.backtest import maps_from_frame
from oap.analytics.config import DEFAULT_CONFIG, PRODUCTION_MAP_ID
from oap.analytics.scoring import ENTRY_RULE
from oap.api import db
from oap.api.db import GoldReader, Query, Signature, db_signature
from oap.api.errors import DatabaseBusy, DatabaseMissing, GoldMissing, NotFound
from oap.api.landscape import (
    ChosenMap,
    MapMeta,
    QuotesBundle,
    SessionBundle,
    build_quotes_bundle,
    finite_or_none,
    named_map,
    pick_map,
    session_bundle,
)
from oap.api.models import (
    CalibrationSummary,
    ChainResponse,
    DistributionResponse,
    HealthResponse,
    HeatmapResponse,
    MapChoice,
    MetricValue,
    SessionsResponse,
    SpreadDetail,
    SpreadsResponse,
    Underlying,
    UnderlyingsResponse,
)
from oap.api.settings import ApiSettings
from oap.api.spreads import (
    SpreadFilters,
    filter_spreads,
    order_spreads,
    prepare_spreads,
    spread_detail,
    spread_rows,
)
from oap.engine.calibration import CalibrationMap

OVERALL: Final = "overall"
"""``segment_type`` of the metrics that cover the whole out-of-sample sample."""

VARIANTS: Final[Mapping[str, Literal["raw", "calibrated", "delta"]]] = {
    "raw": "raw",
    "calibrated": "calibrated",
    "delta": "delta",
}
"""Metric variants the API reports, in display order."""


class _Lru[K: Hashable, V]:
    """A least-recently-used mapping of fixed size, built on ``OrderedDict``."""

    def __init__(self, size: int) -> None:
        """Create an empty cache.

        Args:
            size: Most entries kept; at least 1.
        """
        self._size = max(1, size)
        self._items: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        """Return an entry and mark it as the most recently used.

        Args:
            key: The key.

        Returns:
            The value, or None when absent.
        """
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key: K, value: V) -> None:
        """Add an entry, evicting the least recently used one when full.

        Args:
            key: The key.
            value: The value.
        """
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def drop_if(self, predicate: Callable[[K], bool]) -> None:
        """Remove every entry whose key satisfies a predicate.

        Args:
            predicate: Called with each key.
        """
        for key in [k for k in self._items if predicate(k)]:
            del self._items[key]

    def __len__(self) -> int:
        """Return the number of entries.

        Returns:
            The entry count.
        """
        return len(self._items)


@dataclass(frozen=True)
class Served[T]:
    """A value and whether it came from the last good data while the file was locked.

    Attributes:
        value: The response.
        stale: True when a writer held the lock and the entry is from an older signature.
    """

    value: T
    stale: bool


@dataclass(frozen=True, eq=False)
class _UnderlyingsData:
    """The underlyings table and the latest session."""

    response: UnderlyingsResponse
    latest: date


@dataclass(frozen=True, eq=False)
class _SpreadsData:
    """The prepared spread table with its facets."""

    frame: pd.DataFrame
    as_of: date | None
    underlyings: list[str]
    expirations: list[date]


@dataclass(frozen=True, eq=False)
class _MapsData:
    """The calibration maps with their provenance."""

    maps: Mapping[str, CalibrationMap]
    meta: Mapping[str, MapMeta]


@dataclass
class _Tables:
    """The table groups loaded for one signature; each is loaded on first use."""

    underlyings: _UnderlyingsData | None = None
    spreads: _SpreadsData | None = None
    maps: _MapsData | None = None
    metrics: pd.DataFrame | None = None


def _as_date(value: Any) -> date | None:
    """Convert a timestamp or null to a date.

    Args:
        value: A pandas timestamp, a date, NaT or None.

    Returns:
        The date, or None for a null.
    """
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(str(value)).date()


class GoldStore:
    """Cached, thread-safe access to everything the API serves."""

    def __init__(self, settings: ApiSettings) -> None:
        """Create an empty store; nothing is read until the first request.

        Args:
            settings: Where the database is and how big the caches are.
        """
        self._path = settings.duckdb_path
        self._reader = GoldReader(settings.duckdb_path, settings.duckdb_config)
        self._lock = RLock()
        self._tables: dict[Signature, _Tables] = {}
        self._quotes = _Lru[tuple[Signature, str], QuotesBundle](settings.quotes_cache)
        self._sessions = _Lru[tuple[Signature, str, date, str], SessionBundle](
            settings.session_cache
        )
        self._last_good: Signature | None = None
        self._last_good_at: datetime | None = None

    # -- request plumbing -------------------------------------------------------------

    def _serve[T](self, fetch: Callable[[Signature, bool], T]) -> Served[T]:
        """Run a fetch against the current signature, falling back to the last good one.

        Args:
            fetch: Called with a signature and whether it may read the database; it must
                raise ``DatabaseBusy`` when it needs a read that is not allowed or fails.

        Returns:
            The value; ``stale`` is true when the file is locked and the value comes from
            the entries of the last good signature.

        Raises:
            DatabaseMissing: If the file does not exist.
            DatabaseBusy: If the file is locked and the last good entries cannot answer.
            GoldMissing: If a gold table or column is missing.
            NotFound: If the requested item does not exist.
        """
        with self._lock:
            sig = db_signature(self._path)
            try:
                value = fetch(sig, True)
            except DatabaseBusy:
                last = self._last_good
                if last is None or last == sig:
                    raise
                return Served(fetch(last, False), stale=True)
            if sig != self._last_good:
                self._adopt(sig)
            return Served(value, stale=False)

    def _adopt(self, sig: Signature) -> None:
        """Record a signature as the last good one and drop the entries of older ones.

        Args:
            sig: The signature that was just loaded successfully.
        """
        self._last_good = sig
        self._last_good_at = datetime.now(UTC)
        for old in [s for s in self._tables if s != sig]:
            del self._tables[old]
        self._quotes.drop_if(lambda key: key[0] != sig)
        self._sessions.drop_if(lambda key: key[0] != sig)

    def _read(self, allow: bool, queries: list[Query]) -> list[pd.DataFrame]:
        """Read from the database when allowed.

        Args:
            allow: False in the cache-only fallback.
            queries: ``(sql, params)`` pairs for one connection.

        Returns:
            One frame per query.

        Raises:
            DatabaseBusy: If reading is not allowed or the writer holds the lock.
        """
        if not allow:
            raise DatabaseBusy("the entry is not cached")
        return self._reader.read_many(queries)

    # -- table groups -----------------------------------------------------------------

    def _group(self, sig: Signature) -> _Tables:
        """Return the table groups of a signature, creating the holder if needed.

        Args:
            sig: The file signature.

        Returns:
            The mutable holder.
        """
        return self._tables.setdefault(sig, _Tables())

    def _underlyings_data(self, sig: Signature, allow: bool) -> _UnderlyingsData:
        """Return the underlyings and the latest session, loading them once per signature.

        Args:
            sig: The file signature.
            allow: Whether the database may be read.

        Returns:
            The underlyings data.

        Raises:
            GoldMissing: If the quote table is empty.
        """
        group = self._group(sig)
        if group.underlyings is None:
            frame, latest = self._read(
                allow, [(db.UNDERLYINGS_SQL, ()), (db.LATEST_SESSION_SQL, ())]
            )
            newest = _as_date(latest["latest_session"].iloc[0]) if not latest.empty else None
            if newest is None:
                raise GoldMissing("gold.fct_option_quote has no rows")
            rows = [
                Underlying(
                    symbol=str(r.symbol),
                    sector="" if pd.isna(r.sector) else str(r.sector),
                    first_session=pd.Timestamp(str(r.first_session)).date(),
                    last_session=pd.Timestamp(str(r.last_session)).date(),
                    n_sessions=int(str(r.n_sessions)),
                )
                for r in frame.itertuples(index=False)
            ]
            group.underlyings = _UnderlyingsData(
                UnderlyingsResponse(underlyings=rows, latest_session=newest), newest
            )
        return group.underlyings

    def _spreads_data(self, sig: Signature, allow: bool) -> _SpreadsData:
        """Return the prepared spread table, loading it once per signature.

        Args:
            sig: The file signature.
            allow: Whether the database may be read.

        Returns:
            The spreads data.
        """
        group = self._group(sig)
        if group.spreads is None:
            frame = prepare_spreads(self._read(allow, [(db.SPREADS_SQL, ())])[0])
            as_of = _as_date(frame["trade_date"].max()) if not frame.empty else None
            group.spreads = _SpreadsData(
                frame=frame,
                as_of=as_of,
                underlyings=sorted(frame["underlying"].astype(str).unique().tolist()),
                expirations=sorted(
                    {pd.Timestamp(e).date() for e in frame["expiration"].unique().tolist()}
                ),
            )
        return group.spreads

    def _maps_data(self, sig: Signature, allow: bool) -> _MapsData:
        """Return the calibration maps and their provenance, loading them once per signature.

        Args:
            sig: The file signature.
            allow: Whether the database may be read.

        Returns:
            The maps data.
        """
        group = self._group(sig)
        if group.maps is None:
            frame = self._read(allow, [(db.MAPS_SQL, ())])[0]
            meta: dict[str, MapMeta] = {}
            for map_id, part in frame.groupby("map_id", sort=True):
                head = part.iloc[0]
                fold = head["fold"]
                meta[str(map_id)] = MapMeta(
                    fold=None if pd.isna(fold) else int(fold),
                    train_cutoff=_as_date(head["train_cutoff"]),
                    train_max_expiration=_as_date(head["train_max_expiration"]),
                    n_samples=int(head["n_samples"]),
                )
            group.maps = _MapsData(maps_from_frame(frame), meta)
        return group.maps

    def _metrics(self, sig: Signature, allow: bool) -> pd.DataFrame:
        """Return the overall calibration metrics, loading them once per signature.

        Args:
            sig: The file signature.
            allow: Whether the database may be read.

        Returns:
            Rows of ``gold.calibration_metrics`` with ``segment_type`` ``overall``.
        """
        group = self._group(sig)
        if group.metrics is None:
            group.metrics = self._read(allow, [(db.METRICS_SQL, (OVERALL,))])[0]
        return group.metrics

    # -- bundles ----------------------------------------------------------------------

    def _quotes_bundle(self, sig: Signature, symbol: str, allow: bool) -> QuotesBundle:
        """Return all quotes of one underlying, loading them once per signature.

        Args:
            sig: The file signature.
            symbol: Ticker symbol.
            allow: Whether the database may be read.

        Returns:
            The indexed quotes.

        Raises:
            NotFound: If the underlying has no quotes.
        """
        key = (sig, symbol)
        cached = self._quotes.get(key)
        if cached is not None:
            return cached
        quotes, outcomes = self._read(
            allow, [(db.QUOTES_SQL, (symbol,)), (db.OUTCOMES_SQL, (symbol,))]
        )
        if quotes.empty:
            raise NotFound(f"unknown underlying: {symbol}")
        quotes["option_right"] = quotes["option_right"].astype("category")
        quotes["underlying"] = quotes["underlying"].astype("category")
        bundle = build_quotes_bundle(quotes, outcomes)
        self._quotes.put(key, bundle)
        return bundle

    def _bundle(
        self, sig: Signature, symbol: str, session: date, chosen: ChosenMap, allow: bool
    ) -> SessionBundle:
        """Return the computed bundle of one session and map, computing it once.

        Args:
            sig: The file signature.
            symbol: Ticker symbol.
            session: Trade date.
            chosen: The calibration map to apply.
            allow: Whether the database may be read.

        Returns:
            The session bundle.

        Raises:
            NotFound: If the underlying has no quotes on that date.
        """
        key = (sig, symbol, session, chosen.map_id)
        cached = self._sessions.get(key)
        if cached is not None:
            return cached
        quotes = self._quotes_bundle(sig, symbol, allow)
        rows = quotes.session_quotes(session)
        if rows is None:
            raise NotFound(f"{symbol} has no session {session}")
        bundle = session_bundle(symbol, session, rows, quotes.outcomes, chosen)
        self._sessions.put(key, bundle)
        return bundle

    def _chosen(self, sig: Signature, session: date, choice: MapChoice, allow: bool) -> ChosenMap:
        """Pick the calibration map for a session.

        Args:
            sig: The file signature.
            session: Trade date.
            choice: The requested selection.
            allow: Whether the database may be read.

        Returns:
            The chosen map.
        """
        latest = self._underlyings_data(sig, allow).latest
        maps = self._maps_data(sig, allow)
        return pick_map(choice, session, latest, maps.maps, maps.meta)

    # -- public queries ---------------------------------------------------------------

    def underlyings(self) -> Served[UnderlyingsResponse]:
        """List the underlyings and the latest session.

        Returns:
            Every underlying that has quotes.
        """
        return self._serve(lambda sig, allow: self._underlyings_data(sig, allow).response)

    def sessions(self, symbol: str) -> Served[SessionsResponse]:
        """List the sessions of an underlying.

        Args:
            symbol: Ticker symbol.

        Returns:
            One summary per trade date, ascending.
        """
        return self._serve(
            lambda sig, allow: SessionsResponse(
                symbol=symbol, sessions=self._quotes_bundle(sig, symbol, allow).sessions
            )
        )

    def chain(self, symbol: str, session: date) -> Served[ChainResponse]:
        """Return the option chain of one session.

        Args:
            symbol: Ticker symbol.
            session: Trade date.

        Returns:
            The chain.
        """

        def fetch(sig: Signature, allow: bool) -> ChainResponse:
            chosen = self._chosen(sig, session, "auto", allow)
            return self._bundle(sig, symbol, session, chosen, allow).chain

        return self._serve(fetch)

    def distribution(
        self, symbol: str, session: date, choice: MapChoice
    ) -> Served[DistributionResponse]:
        """Return the distributions of one session.

        Args:
            symbol: Ticker symbol.
            session: Trade date.
            choice: The calibration map selection.

        Returns:
            The distributions, with ``map_choice`` set to ``choice``.
        """

        def fetch(sig: Signature, allow: bool) -> DistributionResponse:
            chosen = self._chosen(sig, session, choice, allow)
            found = self._bundle(sig, symbol, session, chosen, allow).distribution
            return found.model_copy(update={"map_choice": choice})

        return self._serve(fetch)

    def heatmap(self, symbol: str, session: date, choice: MapChoice) -> Served[HeatmapResponse]:
        """Return the probability heatmap of one session.

        Args:
            symbol: Ticker symbol.
            session: Trade date.
            choice: The calibration map selection.

        Returns:
            The heatmap.
        """

        def fetch(sig: Signature, allow: bool) -> HeatmapResponse:
            chosen = self._chosen(sig, session, choice, allow)
            return self._bundle(sig, symbol, session, chosen, allow).heatmap

        return self._serve(fetch)

    def spreads(self, filters: SpreadFilters) -> Served[SpreadsResponse]:
        """List the scored spreads that match the filters.

        Args:
            filters: The filters and the row limit.

        Returns:
            The matching rows with the facets of the whole table.
        """

        def fetch(sig: Signature, allow: bool) -> SpreadsResponse:
            data = self._spreads_data(sig, allow)
            matched = order_spreads(filter_spreads(data.frame, filters), filters.sort)
            return SpreadsResponse(
                as_of=data.as_of,
                source="gold",
                total=len(data.frame),
                matched=len(matched),
                min_prob_profit=DEFAULT_CONFIG.min_prob_profit,
                underlyings=data.underlyings,
                expirations=data.expirations,
                sort=filters.sort,
                entry_rule=ENTRY_RULE,
                rows=spread_rows(matched, filters.limit),
            )

        return self._serve(fetch)

    def spread(self, spread_key: str) -> Served[SpreadDetail]:
        """Return one spread with its payoff curve and densities.

        Args:
            spread_key: The ``spread_key`` of a gold row.

        Returns:
            The detail.

        Raises:
            NotFound: If no row has the key, or its expiration has no distribution.
            GoldMissing: If the row's calibration map is not in ``gold.calibration_map``.
        """

        def fetch(sig: Signature, allow: bool) -> SpreadDetail:
            frame = self._spreads_data(sig, allow).frame
            found = frame.loc[frame["spread_key"] == spread_key]
            if found.empty:
                raise NotFound(f"unknown spread: {spread_key}")
            row = found.iloc[0]
            session = pd.Timestamp(str(row["trade_date"])).date()
            maps = self._maps_data(sig, allow)
            chosen = named_map(str(row["map_id"]), session, maps.maps, maps.meta)
            if chosen is None:
                raise GoldMissing(f"gold.calibration_map has no map {row['map_id']}")
            bundle = self._bundle(sig, str(row["underlying"]), session, chosen, allow)
            curves = bundle.curves.get(pd.Timestamp(str(row["expiration"])).date())
            if curves is None:
                raise NotFound(f"no distribution for the expiration of {spread_key}")
            return spread_detail(row, curves)

        return self._serve(fetch)

    def calibration_summary(self) -> Served[CalibrationSummary]:
        """Summarise the production map and its out-of-sample metrics.

        Returns:
            The overall metrics with their intervals.
        """

        def fetch(sig: Signature, allow: bool) -> CalibrationSummary:
            frame = self._metrics(sig, allow)
            maps = self._maps_data(sig, allow)
            production = maps.meta.get(PRODUCTION_MAP_ID)
            known = frame.loc[frame["variant"].isin(list(VARIANTS))]
            order = {name: i for i, name in enumerate(VARIANTS)}
            ordered = known.assign(order=known["variant"].map(order)).sort_values(
                ["metric", "order"], kind="stable"
            )
            metrics = [
                MetricValue(
                    metric=str(r.metric),
                    variant=VARIANTS[str(r.variant)],
                    value=finite_or_none(r.value),
                    ci_low=finite_or_none(r.ci_low),
                    ci_high=finite_or_none(r.ci_high),
                )
                for r in ordered.itertuples(index=False)
            ]
            counts = frame.iloc[0] if not frame.empty else None
            return CalibrationSummary(
                map_id=PRODUCTION_MAP_ID,
                n_samples=0 if production is None else production.n_samples,
                train_max_expiration=None
                if production is None
                else production.train_max_expiration,
                first_test_year=DEFAULT_CONFIG.first_test_year,
                n_predictions=0 if counts is None else int(counts["n_predictions"]),
                n_snapshots=0 if counts is None else int(counts["n_snapshots"]),
                n_clusters=0 if counts is None else int(counts["n_clusters"]),
                metrics=metrics,
            )

        return self._serve(fetch)

    def health(self) -> HealthResponse:
        """Report the state of the database file without raising.

        Returns:
            ``db`` is ``missing`` without the file, ``ok`` when the data in memory matches
            the file or the file opens, and ``busy`` when a writer holds the lock.
        """
        with self._lock:
            state: Literal["ok", "busy", "missing"] = "ok"
            try:
                sig = db_signature(self._path)
                if sig != self._last_good:
                    self._reader.read("select 1")
            except DatabaseMissing:
                state = "missing"
            except DatabaseBusy:
                state = "busy"
            return HealthResponse(
                status="ok",
                db=state,
                db_path=self._path.name,
                last_good_signature_at=self._last_good_at,
            )
