import { useMemo } from 'react';
import { busyError, terminalError, useSpreadDetail, useSpreads } from '../api/queries';
import type { SpreadRow } from '../api/types';
import { PayoffChart } from '../charts/PayoffChart';
import { SpreadScatter } from '../charts/SpreadScatter';
import { CalibrationBadge } from '../components/CalibrationBadge';
import { Chip } from '../components/Chip';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { NumberField, SliderField, SwitchField } from '../components/FilterFields';
import { Measured } from '../components/Measured';
import { MultiSelect } from '../components/MultiSelect';
import { Select } from '../components/Select';
import { StatTile } from '../components/StatTile';
import { orderFlags } from '../lib/flags';
import {
  annualisedRoc,
  expiryLabel,
  longDate,
  num,
  pct,
  shortDate,
  signedPct,
  strike,
  usd,
} from '../lib/format';
import { MAX_HIGHLIGHTS, useHighlightSlots, useSpreadFilters } from '../state/useSpreadFilters';

const COLUMNS: Column<SpreadRow>[] = [
  {
    key: 'rank',
    header: 'Rank',
    align: 'right',
    sortValue: (r) => r.rank,
    cell: (r) => (r.rank === null ? '–' : r.rank),
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
    key: 'p_max_loss',
    header: 'P(max loss)',
    align: 'right',
    sortValue: (r) => r.prob_max_loss,
    cell: (r) => pct(r.prob_max_loss),
  },
  {
    key: 'roc',
    header: 'E[ROC]',
    align: 'right',
    sortValue: (r) => r.expected_roc,
    cell: (r) => pct(r.expected_roc, 2),
  },
  {
    key: 'ann_roc',
    header: 'Ann. ROC',
    align: 'right',
    sortValue: (r) => r.annualised_roc,
    cell: (r) => annualisedRoc(r.annualised_roc),
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
    const top = rows
      .filter((row) => row.rank !== null && row.rank <= 3)
      .map((row) => row.underlying);
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

  return (
    <div className="page">
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
                <Measured>
                  {(width) => (
                    <SpreadScatter
                      rows={rows}
                      highlights={slotted}
                      selectedKey={filters.selected}
                      onSelect={select}
                      minProbProfit={data.min_prob_profit}
                      width={width}
                      height={Math.round(Math.min(460, Math.max(300, width * 0.6)))}
                      refreshing={refreshing}
                    />
                  )}
                </Measured>
              )}
            </section>

            <section className="card block detail" aria-label="Spread detail">
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
                      value={usd(spread.credit)}
                      sub={`natural ${usd(spread.credit_natural)}`}
                    />
                    <StatTile label="Max loss" value={usd(spread.max_loss)} />
                    <StatTile label="Breakeven" value={usd(spread.breakeven)} />
                    <StatTile
                      label="POP"
                      value={pct(spread.prob_profit)}
                      sub={`raw ${pct(spread.prob_profit_raw)}`}
                    />
                    <StatTile label="P(max loss)" value={pct(spread.prob_max_loss)} />
                    <StatTile
                      label="E[ROC]"
                      value={signedPct(spread.expected_roc, 2)}
                      sub={`raw ${signedPct(spread.expected_roc_raw, 2)}`}
                    />
                    <StatTile label="Interest" value={usd(spread.interest)} />
                    <StatTile label="Kelly" value={pct(spread.kelly_fraction)} />
                  </div>
                  <Measured>
                    {(width) => <PayoffChart detail={spread} width={width} height={340} />}
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
              caption="Put credit spreads"
              columns={COLUMNS}
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
