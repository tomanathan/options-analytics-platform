import { useMemo } from 'react';
import { busyError, terminalError, useSpreadDetail, useSpreads } from '../api/queries';
import type { SpreadRow, SpreadSort } from '../api/types';
import { MispricingScatter } from '../charts/MispricingScatter';
import { PayoffChart } from '../charts/PayoffChart';
import { PopGapScatter } from '../charts/PopGapScatter';
import { SpreadScatter } from '../charts/SpreadScatter';
import { CalibrationBadge } from '../components/CalibrationBadge';
import { Chip } from '../components/Chip';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/EmptyState';
import { EntryCard } from '../components/EntryCard';
import { ErrorState } from '../components/ErrorState';
import { NumberField, SliderField, SwitchField } from '../components/FilterFields';
import { Measured } from '../components/Measured';
import { MultiSelect } from '../components/MultiSelect';
import { Select } from '../components/Select';
import { SegmentedToggle } from '../components/SegmentedToggle';
import { StatTile } from '../components/StatTile';
import { orderFlags } from '../lib/flags';
import {
  annualisedRoc,
  expiryLabel,
  longDate,
  num,
  pct,
  ratio,
  shortDate,
  signedPct,
  signedPoints,
  strike,
  usd,
} from '../lib/format';
import { MAX_HIGHLIGHTS, useHighlightSlots, useSpreadFilters } from '../state/useSpreadFilters';

/** Interest arrives in dollars per share (often under a cent); the tile shows one contract. */
const SHARES_PER_CONTRACT = 100;

/** Pixels reserved by the charts until their width is measured (see `Measured`). */
const SCATTER_MIN_HEIGHT = 460;
const PAYOFF_HEIGHT = 340;

const RANK_OPTIONS: { value: SpreadSort; label: string }[] = [
  { value: 'return', label: 'Return on max loss' },
  { value: 'edge', label: 'Edge' },
  { value: 'reward_to_risk', label: 'Reward/risk' },
  { value: 'kelly', label: 'Kelly' },
  { value: 'pop', label: 'POP' },
  { value: 'pop_gap', label: 'POP gap' },
  { value: 'entry', label: 'Entry' },
];

const rankLabel = (sort: SpreadSort) =>
  RANK_OPTIONS.find((option) => option.value === sort)?.label ?? sort;

/** Columns of the spreads table. "#" is the 1-based position in the server's order for `sort`. */
function makeColumns(
  sort: SpreadSort,
  positions: ReadonlyMap<string, number>,
): Column<SpreadRow>[] {
  const position = (row: SpreadRow) => positions.get(row.spread_key) ?? null;
  return [
    {
      key: 'rank',
      header: `Rank · ${rankLabel(sort)}`,
      align: 'right',
      title: 'Position in the order the server returned for this ranking.',
      sortValue: position,
      cell: (r) => position(r) ?? '–',
    },
    {
      key: 'underlying',
      header: 'Underlying',
      sortValue: (r) => r.underlying,
      cell: (r) => r.underlying,
    },
    {
      key: 'expiration',
      header: 'Exp (DTE)',
      sortValue: (r) => r.expiration,
      cell: (r) => expiryLabel(r.expiration, r.dte_days),
    },
    {
      key: 'strikes',
      header: 'Short/Long',
      align: 'right',
      sortValue: (r) => r.short_strike,
      cell: (r) => `${strike(r.short_strike)}/${strike(r.long_strike)}`,
    },
    {
      key: 'width',
      header: 'Width',
      align: 'right',
      sortValue: (r) => r.width,
      cell: (r) => num(r.width, 1),
    },
    {
      key: 'credit',
      header: 'Credit',
      align: 'right',
      sortValue: (r) => r.credit,
      cell: (r) => num(r.credit),
    },
    {
      key: 'natural',
      header: 'Natural',
      align: 'right',
      sortValue: (r) => r.credit_natural,
      cell: (r) => num(r.credit_natural),
    },
    {
      key: 'fair',
      header: 'Fair credit',
      align: 'right',
      title: 'Calibrated fair credit, $/sh',
      sortValue: (r) => r.fair_credit,
      cell: (r) => num(r.fair_credit),
    },
    {
      key: 'pop',
      header: 'POP cal',
      align: 'right',
      sortValue: (r) => r.prob_profit,
      cell: (r) => pct(r.prob_profit),
    },
    {
      key: 'pop_raw',
      header: 'POP raw',
      align: 'right',
      sortValue: (r) => r.prob_profit_raw,
      cell: (r) => pct(r.prob_profit_raw),
    },
    {
      key: 'pop_implied',
      header: 'Implied POP',
      align: 'right',
      title: 'Price-implied probability of profit: max loss over width',
      sortValue: (r) => r.pop_implied,
      cell: (r) => pct(r.pop_implied),
    },
    {
      key: 'pop_gap',
      header: 'POP gap (pts)',
      align: 'right',
      title: 'Calibrated POP minus price-implied POP, in percentage points',
      sortValue: (r) => r.pop_gap,
      cell: (r) => signedPoints(r.pop_gap),
    },
    {
      key: 'p_max_loss',
      header: 'P(max loss)',
      align: 'right',
      sortValue: (r) => r.prob_max_loss,
      cell: (r) => pct(r.prob_max_loss),
    },
    {
      key: 'roc',
      header: 'E[R/max loss]',
      align: 'right',
      sortValue: (r) => r.expected_roc,
      cell: (r) => pct(r.expected_roc, 2),
    },
    {
      key: 'ann_roc',
      header: 'Ann. R/max loss',
      align: 'right',
      sortValue: (r) => r.annualised_roc,
      cell: (r) => annualisedRoc(r.annualised_roc),
    },
    {
      key: 'edge',
      header: 'Edge $',
      align: 'right',
      title: 'Mid credit minus calibrated fair credit, $/sh',
      sortValue: (r) => r.edge,
      cell: (r) => num(r.edge),
    },
    {
      key: 'edge_pct',
      header: 'Edge %',
      align: 'right',
      title: 'Edge as a share of the mid credit',
      sortValue: (r) => r.edge_pct,
      cell: (r) => pct(r.edge_pct),
    },
    {
      key: 'reward_to_risk',
      header: 'Reward/risk',
      align: 'right',
      title: 'Expected payoff over payoff standard deviation, per trade, not annualised',
      sortValue: (r) => r.reward_to_risk,
      cell: (r) => ratio(r.reward_to_risk),
    },
    {
      key: 'kelly',
      header: 'Kelly',
      align: 'right',
      sortValue: (r) => r.kelly_fraction,
      cell: (r) => pct(r.kelly_fraction),
    },
    {
      key: 'flags',
      header: 'Flags',
      cell: (r) => (
        <span className="chips">
          {orderFlags(r.flags).map((flag) => (
            <Chip key={flag.flag} kind={flag.kind} icon={flag.icon} title={flag.meaning}>
              {flag.label}
            </Chip>
          ))}
          {r.extrapolated && (
            <Chip
              kind="warning"
              icon={'⚠'}
              title="The short or long strike lies outside the quoted strikes."
            >
              extrapolated
            </Chip>
          )}
        </span>
      ),
    },
  ];
}

const DETAIL_ID = 'spread-detail';

const rowKey = (row: SpreadRow) => row.spread_key;

export default function SpreadsPage() {
  const { filters, query, update } = useSpreadFilters();
  const spreads = useSpreads(query);
  const detail = useSpreadDetail(filters.selected);

  const data = spreads.data;
  const spread = detail.data;
  const rows = useMemo(() => data?.rows ?? [], [data]);

  const highlights = useMemo(() => {
    if (filters.highlights !== null) return filters.highlights;
    const top = rows.filter((row) => row.eligible).map((row) => row.underlying);
    return [...new Set(top)].slice(0, MAX_HIGHLIGHTS);
  }, [filters.highlights, rows]);
  const slotted = useHighlightSlots(highlights);

  const busy = busyError(spreads, detail);
  const failure = terminalError(spreads);
  const refreshing = spreads.isPlaceholderData;

  const underlyingOptions = useMemo(
    () =>
      [...new Set([...(data?.underlyings ?? []), ...filters.underlyings, ...highlights])].sort(),
    [data, filters.underlyings, highlights],
  );
  const expirationOptions = [
    { value: '', label: 'All expirations' },
    ...[
      ...new Set([
        ...(data?.expirations ?? []),
        ...(filters.expiration ? [filters.expiration] : []),
      ]),
    ]
      .sort()
      .map((e) => ({ value: e, label: shortDate(e) })),
  ];

  const select = (row: SpreadRow) => update({ selected: row.spread_key }, { replace: true });
  const showDetail = (row: SpreadRow) => {
    select(row);
    document.getElementById(DETAIL_ID)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  };

  const sort = data?.sort ?? filters.rankBy;
  const columns = useMemo(
    () => makeColumns(sort, new Map(rows.map((row, index) => [row.spread_key, index + 1]))),
    [sort, rows],
  );

  return (
    <div className="page">
      <EntryCard selectedKey={filters.selected} onSelect={showDetail} />

      <section className="controls" aria-label="Spread filters">
        <MultiSelect
          label="Underlying"
          options={underlyingOptions}
          selected={filters.underlyings}
          emptyLabel="All underlyings"
          onChange={(underlyings) => update({ underlyings })}
        />
        <Select
          label="Expiration"
          value={filters.expiration ?? ''}
          options={expirationOptions}
          onChange={(value) => update({ expiration: value === '' ? null : value })}
        />
        <NumberField
          label="Min width ($)"
          value={filters.minWidth}
          placeholder="any"
          onCommit={(minWidth) => update({ minWidth })}
        />
        <NumberField
          label="Max width ($)"
          value={filters.maxWidth}
          placeholder="any"
          onCommit={(maxWidth) => update({ maxWidth })}
        />
        <SliderField
          label="Min POP"
          value={filters.minPop}
          min={0}
          max={1}
          step={0.01}
          format={(v) => pct(v, 0)}
          onCommit={(minPop) => update({ minPop })}
        />
        <NumberField
          label="Min credit ($)"
          value={filters.minCredit > 0 ? filters.minCredit : null}
          placeholder="0"
          step={0.05}
          onCommit={(minCredit) => update({ minCredit: minCredit ?? 0 })}
        />
        <NumberField
          label="Min edge (%)"
          value={filters.minEdgePct === null ? null : Number((filters.minEdgePct * 100).toFixed(4))}
          placeholder="any"
          step={1}
          onCommit={(value) =>
            update({ minEdgePct: value === null ? null : Number((value / 100).toFixed(6)) })
          }
        />
        <SegmentedToggle
          label="Rank by"
          value={filters.rankBy}
          options={RANK_OPTIONS}
          onChange={(rankBy) => update({ rankBy })}
        />
        <SwitchField
          label="Eligible only"
          checked={filters.eligibleOnly}
          onChange={(eligibleOnly) => update({ eligibleOnly })}
        />
        <MultiSelect
          label="Highlight"
          options={underlyingOptions}
          selected={highlights}
          emptyLabel="None"
          max={MAX_HIGHLIGHTS}
          onChange={(next) => update({ highlights: next }, { replace: true })}
        />
        <div className="controls__chips">
          <CalibrationBadge variant="full" />
        </div>
      </section>

      {busy && <ErrorState error={busy} variant="banner" />}
      {failure && !busy && <ErrorState error={failure} />}
      {!data && !failure && !busy && <EmptyState title="Loading spreads…" />}

      {data && (
        <>
          <p className="summary" aria-live="polite">
            <strong>{data.matched.toLocaleString('en-US')}</strong> of{' '}
            {data.total.toLocaleString('en-US')} spreads
            {data.as_of ? ` · session ${longDate(data.as_of)}` : ''}
            {data.source === 'recomputed' ? ' · recomputed' : ''}
          </p>

          <div className="spreads-grid">
            <section className="card block" aria-label="Probability of profit against return">
              <div className="block__head">
                <h2>POP against expected return</h2>
              </div>
              {rows.length === 0 ? (
                <EmptyState
                  title="No spreads match these filters"
                  hint="Widen the filters or switch off Eligible only."
                />
              ) : (
                <Measured minHeight={SCATTER_MIN_HEIGHT}>
                  {(width) => (
                    <SpreadScatter
                      rows={rows}
                      highlights={slotted}
                      selectedKey={filters.selected}
                      onSelect={select}
                      minProbProfit={data.min_prob_profit}
                      width={width}
                      height={Math.round(Math.min(SCATTER_MIN_HEIGHT, Math.max(300, width * 0.6)))}
                      refreshing={refreshing}
                    />
                  )}
                </Measured>
              )}
            </section>

            {rows.length > 0 && (
              <section className="card block" aria-label="Market against fair credit">
                <div className="block__head">
                  <h2>Market vs calibrated fair credit</h2>
                </div>
                <Measured minHeight={SCATTER_MIN_HEIGHT}>
                  {(width) => (
                    <MispricingScatter
                      rows={rows}
                      highlights={slotted}
                      selectedKey={filters.selected}
                      onSelect={select}
                      width={width}
                      height={Math.round(Math.min(SCATTER_MIN_HEIGHT, Math.max(300, width * 0.6)))}
                      refreshing={refreshing}
                    />
                  )}
                </Measured>
              </section>
            )}

            {rows.length > 0 && (
              <section className="card block" aria-label="Calibrated against price-implied POP">
                <div className="block__head">
                  <h2>Calibrated vs price-implied probability of profit</h2>
                </div>
                <p className="card__note">
                  The same information as the fair-credit chart, in probability units instead of
                  dollars.
                </p>
                <Measured minHeight={SCATTER_MIN_HEIGHT}>
                  {(width) => (
                    <PopGapScatter
                      rows={rows}
                      highlights={slotted}
                      selectedKey={filters.selected}
                      onSelect={select}
                      width={width}
                      height={Math.round(Math.min(SCATTER_MIN_HEIGHT, Math.max(300, width * 0.6)))}
                      refreshing={refreshing}
                    />
                  )}
                </Measured>
              </section>
            )}

            <section className="card block detail" id={DETAIL_ID} aria-label="Spread detail">
              <div className="block__head">
                <h2>
                  {spread
                    ? `${spread.underlying} ${strike(spread.short_strike)}/${strike(spread.long_strike)} · ${expiryLabel(spread.expiration, spread.dte_days)}`
                    : 'Spread detail'}
                </h2>
              </div>
              {filters.selected === null && (
                <EmptyState
                  title="Select a spread"
                  hint="Click a point or a table row to see its payoff over the density."
                />
              )}
              {filters.selected !== null && detail.isError && <ErrorState error={detail.error} />}
              {filters.selected !== null && !spread && !detail.isError && (
                <EmptyState title="Loading spread…" />
              )}
              {spread && filters.selected !== null && (
                <div className={detail.isPlaceholderData ? 'is-refreshing' : undefined}>
                  <div className="stats">
                    <StatTile
                      label="Credit"
                      unit="$/sh"
                      value={usd(spread.credit)}
                      sub={`natural ${usd(spread.credit_natural)}`}
                    />
                    <StatTile label="Max loss" unit="$/sh" value={usd(spread.max_loss)} />
                    <StatTile label="Breakeven" unit="$/sh" value={usd(spread.breakeven)} />
                    <StatTile
                      label="POP"
                      value={pct(spread.prob_profit)}
                      sub={`raw ${pct(spread.prob_profit_raw)}`}
                    />
                    <StatTile label="P(max loss)" value={pct(spread.prob_max_loss)} />
                    <StatTile
                      label="Exp. return on max loss"
                      value={signedPct(spread.expected_roc, 2)}
                      sub={`raw ${signedPct(spread.expected_roc_raw, 2)}`}
                    />
                    <StatTile
                      label="Interest"
                      unit="per contract"
                      value={usd(spread.interest * SHARES_PER_CONTRACT)}
                    />
                    <StatTile label="Kelly" value={pct(spread.kelly_fraction)} />
                    <StatTile
                      label="Fair credit"
                      unit="$/sh"
                      value={usd(spread.fair_credit)}
                      sub={`raw ${usd(spread.fair_credit_raw)}`}
                    />
                    <StatTile
                      label="Edge"
                      unit="$/sh"
                      value={usd(spread.edge)}
                      sub={`${pct(spread.edge_pct)} of mid · natural ${usd(spread.edge_natural)}`}
                    />
                    <StatTile label="Payoff σ" unit="$/sh" value={usd(spread.payoff_std)} />
                    <StatTile
                      label="Reward/risk"
                      value={ratio(spread.reward_to_risk)}
                      sub="per trade, not annualised"
                    />
                    <StatTile label="Price-implied POP" value={pct(spread.pop_implied)} />
                    <StatTile
                      label="POP gap"
                      unit="pts"
                      value={signedPoints(spread.pop_gap)}
                      sub={`raw gap ${signedPoints(spread.pop_gap_raw)} pts`}
                    />
                  </div>
                  <p className="detail__note">
                    Fair credit applies one pooled calibration map to this chain: a historical
                    average across today&apos;s large caps, not a forecast for this contract.
                    {spread.edge_natural < 0 && ' At the natural credit the gap is negative.'}
                  </p>
                  <Measured minHeight={PAYOFF_HEIGHT}>
                    {(width) => (
                      <PayoffChart detail={spread} width={width} height={PAYOFF_HEIGHT} />
                    )}
                  </Measured>
                </div>
              )}
            </section>
          </div>

          <section className="card block" aria-label="Spreads table">
            <div className="block__head">
              <h2>Spreads</h2>
            </div>
            <DataTable
              key={sort}
              caption="Put credit spreads"
              columns={columns}
              rows={rows}
              rowKey={rowKey}
              pageSize={50}
              selectedKey={filters.selected}
              onSelect={select}
            />
          </section>
        </>
      )}
    </div>
  );
}
