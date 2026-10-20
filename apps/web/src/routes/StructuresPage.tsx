import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  busyError,
  terminalError,
  useDistribution,
  useSessions,
  useStructures,
  useUnderlyings,
} from '../api/queries';
import type {
  Fill,
  MapChoice,
  StructureKindBest,
  StructureRow,
  StructuresResponse,
} from '../api/types';
import { StructurePayoffChart } from '../charts/StructurePayoffChart';
import { Chip } from '../components/Chip';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { NumberField, SliderField, SwitchField } from '../components/FilterFields';
import { KindsTable, premiumLabel, StructureTable } from '../components/KindsTable';
import { Measured } from '../components/Measured';
import { SegmentedToggle } from '../components/SegmentedToggle';
import { Select } from '../components/Select';
import { StatTile } from '../components/StatTile';
import { VerdictCard } from '../components/VerdictCard';
import {
  annualisedRoc,
  expiryLabel,
  longDate,
  multiple,
  num,
  pct,
  ratio,
  signedPct,
  signedPoints,
  strike,
  usd,
} from '../lib/format';
import { KINDS, parseLegs, PRESETS, viewSentence } from '../lib/structures';
import { DEFAULT_UNDERLYING } from '../state/useLandscapeParams';
import { MAX_MIN_POP, useStructureParams } from '../state/useStructureParams';
import type { StructureParams } from '../state/useStructureParams';

/** Premiums and losses arrive in dollars per share; the detail panel also shows one contract. */
const SHARES_PER_CONTRACT = 100;
const CHART_HEIGHT = 420;
const DETAIL_ID = 'structure-detail';

const FILL_OPTIONS = [
  { value: 'natural', label: 'Natural' },
  { value: 'mid', label: 'Mid' },
] as const;
const MAP_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'production', label: 'Production' },
  { value: 'walk_forward', label: 'Walk-forward' },
] as const;

/** A moneyness fraction as the percent-of-close the inputs show: 1.0291 -> 102.9. */
const toPercent = (value: number | null | undefined) =>
  value === null || value === undefined ? null : Number((value * 100).toFixed(1));
const fromPercent = (value: number | null) =>
  value === null ? null : Number((value / 100).toFixed(6));

interface OutcomeRowProps {
  params: StructureParams;
  data: StructuresResponse | undefined;
  onChange: (patch: Partial<StructureParams>) => void;
}

/** Preset chips and the custom range. Editing a bound turns the shown preset into a custom view. */
function OutcomeControls({ params, data, onChange }: OutcomeRowProps) {
  const fromData = params.preset !== null && data?.view.preset === params.preset;
  const lo =
    params.preset === null
      ? toPercent(params.lo)
      : fromData
        ? toPercent(data?.view.lo_moneyness)
        : null;
  const hi =
    params.preset === null
      ? toPercent(params.hi)
      : fromData
        ? toPercent(data?.view.hi_moneyness)
        : null;
  const outside = params.preset === null ? params.outside : (data?.view.outside ?? false);

  const custom = (patch: { lo?: number | null; hi?: number | null; outside?: boolean }) =>
    onChange({
      preset: null,
      lo: fromPercent(patch.lo === undefined ? lo : patch.lo),
      hi: fromPercent(patch.hi === undefined ? hi : patch.hi),
      outside: patch.outside ?? outside,
    });

  return (
    <section className="card outcome" aria-label="Outcome">
      <div className="outcome__row">
        <div className="field">
          <span className="field__label" id="outcome-presets">
            Outcome at expiry
          </span>
          <div className="preset-chips" role="group" aria-labelledby="outcome-presets">
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={params.preset === preset.id ? 'preset is-active' : 'preset'}
                aria-pressed={params.preset === preset.id}
                onClick={() => onChange({ preset: preset.id })}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
        <div className="outcome__custom">
          <NumberField
            label="lo % of close"
            value={lo}
            placeholder="open"
            step={0.5}
            onCommit={(value) => custom({ lo: value })}
          />
          <NumberField
            label="hi % of close"
            value={hi}
            placeholder="open"
            step={0.5}
            onCommit={(value) => custom({ hi: value })}
          />
          <SwitchField
            label="Outside"
            checked={outside}
            onChange={(checked) => custom({ outside: checked })}
          />
          <span className="muted outcome__mode" data-testid="outcome-mode">
            {params.preset === null ? 'custom range' : 'preset bounds'}
          </span>
        </div>
      </div>
      {data && (
        <p className="outcome__sentence" data-testid="view-sentence">
          {viewSentence(data.view)}
        </p>
      )}
    </section>
  );
}

function DetailPanel({
  row,
  fill,
  ranking,
}: {
  row: StructureKindBest | null;
  fill: Fill;
  ranking: readonly StructureRow[];
}) {
  const legs = row ? parseLegs(row.legs) : [];
  return (
    <section className="card block detail" id={DETAIL_ID} aria-label="Structure detail">
      <div className="block__head">
        <h2>{row ? `${KINDS[row.kind].label} · ${row.legs}` : 'Structure detail'}</h2>
      </div>
      {row === null ? (
        <EmptyState title="Select a kind" hint="Click a row of the kinds table to see its legs." />
      ) : (
        <>
          <div className="table-scroll">
            <table className="table table--legs">
              <caption className="visually-hidden">Legs of the {KINDS[row.kind].label}</caption>
              <thead>
                <tr>
                  <th scope="col">Right</th>
                  <th scope="col" className="is-num">
                    Strike
                  </th>
                  <th scope="col">Side</th>
                  <th scope="col">Fill</th>
                </tr>
              </thead>
              <tbody>
                {legs.map((leg) => (
                  <tr key={`${leg.right}-${leg.strike}-${leg.quantity}`}>
                    <td>{leg.right === 'C' ? 'Call' : 'Put'}</td>
                    <td className="is-num">{strike(leg.strike)}</td>
                    <td>{leg.quantity > 0 ? 'Long' : 'Short'}</td>
                    <td>{fill === 'mid' ? 'mid' : leg.quantity > 0 ? 'ask' : 'bid'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="stats detail__stats">
            <StatTile
              label="Premium"
              unit="per contract"
              value={usd(Math.abs(row.net_premium) * SHARES_PER_CONTRACT)}
              sub={premiumLabel(row.net_premium) + ' /sh'}
            />
            <StatTile
              label="Max loss"
              unit="per contract"
              value={usd(row.max_loss * SHARES_PER_CONTRACT)}
              sub={`${usd(row.max_loss)} /sh`}
            />
            <StatTile
              label="Max gain"
              unit="per contract"
              value={row.max_gain === null ? '∞' : usd(row.max_gain * SHARES_PER_CONTRACT)}
            />
            <StatTile label="P(profit | view)" value={pct(row.prob_profit_given_view)} />
            <StatTile label="Return if right" value={multiple(row.return_if_right)} />
            <StatTile label="Return if wrong" value={multiple(row.return_if_wrong)} />
            <StatTile label="Worst in view" value={multiple(row.worst_in_view)} />
            <StatTile
              label="E[R/max loss]"
              value={signedPct(row.expected_return)}
              sub={`annualised ${annualisedRoc(row.annualised_return)}`}
            />
            <StatTile label="P(profit)" value={pct(row.prob_profit)} />
            <StatTile
              label="Reward/risk"
              value={ratio(row.reward_to_risk)}
              sub="per trade, not annualised"
            />
            <StatTile label="P&L σ" unit="$/sh" value={usd(row.pnl_std)} />
            <StatTile label="Tail share" value={pct(row.tail_share, 0)} />
            <StatTile
              label="Breakevens"
              unit="$/sh"
              value={row.breakevens.map((b) => num(b)).join(' · ') || '–'}
            />
          </div>
        </>
      )}
      <details className="ranking">
        <summary>All qualifying structures ({ranking.length})</summary>
        <StructureTable
          caption="All qualifying structures"
          rows={ranking}
          rowKey={(r) => `${r.kind}|${r.legs}`}
        />
      </details>
    </section>
  );
}

export default function StructuresPage() {
  const [search] = useSearchParams();
  const symbol = search.get('symbol') ?? DEFAULT_UNDERLYING;

  const underlyings = useUnderlyings();
  const sessionsQuery = useSessions(symbol);
  // keepPreviousData can hand back the previous underlying's list for a moment; ignore it.
  const sessions = sessionsQuery.data?.symbol === symbol ? sessionsQuery.data.sessions : undefined;
  const dates = useMemo(() => sessions?.map((s) => s.session), [sessions]);
  const { params, query, update } = useStructureParams(dates);

  const distribution = useDistribution(params.symbol, params.session, params.map);
  const structures = useStructures(query);
  const data = structures.data;

  const busy = busyError(sessionsQuery, distribution, structures);
  const failure = terminalError(sessionsQuery, structures);
  const refreshing = structures.isPlaceholderData;

  const symbols = underlyings.data?.underlyings.map((u) => u.symbol) ?? [];
  const symbolOptions = (
    symbols.includes(params.symbol) ? symbols : [params.symbol, ...symbols]
  ).map((s) => ({ value: s, label: s }));
  const sessionOptions = [...(dates ?? [])]
    .reverse()
    .map((d) => ({ value: d, label: longDate(d) }));
  const expirations =
    distribution.data?.symbol === params.symbol ? distribution.data.expirations : [];
  const expirationOptions = [
    {
      value: '',
      label: data
        ? `Nearest 35 days (${expiryLabel(data.expiration, data.dte_days)})`
        : 'Nearest 35 days',
    },
    ...expirations.map((e) => {
      const reason = e.curve === null ? (e.unavailable_reason ?? 'no curve') : null;
      return {
        value: e.expiration,
        label: reason
          ? `${expiryLabel(e.expiration, e.dte_days)} · ${reason}`
          : expiryLabel(e.expiration, e.dte_days),
        disabled: reason !== null,
      };
    }),
  ];

  const kinds = useMemo(() => data?.kinds ?? [], [data]);
  const selectedKind =
    kinds.find((k) => k.kind === params.kind)?.kind ??
    data?.verdict.best_kind ??
    kinds[0]?.kind ??
    null;
  const selectedRow = kinds.find((k) => k.kind === selectedKind) ?? null;

  const select = (row: StructureRow) => {
    update({ kind: row.kind }, { replace: true });
    document.getElementById(DETAIL_ID)?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  };

  return (
    <div className="page">
      <section className="controls" aria-label="Structure controls">
        <Select
          label="Underlying"
          value={params.symbol}
          options={symbolOptions}
          onChange={(symbol) => update({ symbol })}
        />
        <Select
          label="Session"
          value={params.session ?? ''}
          options={sessionOptions.length > 0 ? sessionOptions : [{ value: '', label: 'Loading…' }]}
          disabled={sessionOptions.length === 0}
          onChange={(session) => update({ session })}
        />
        <Select
          label="Expiration"
          value={params.expiration ?? ''}
          options={expirationOptions}
          onChange={(value) => update({ expiration: value === '' ? null : value })}
        />
        <SegmentedToggle<Fill>
          label="Fill"
          value={params.fill}
          options={FILL_OPTIONS}
          onChange={(fill) => update({ fill })}
        />
        <SegmentedToggle<MapChoice>
          label="Calibration map"
          value={params.map}
          options={MAP_OPTIONS}
          onChange={(map) => update({ map })}
        />
        <SliderField
          label="Min P(profit | view)"
          value={params.minPop}
          min={0}
          max={MAX_MIN_POP}
          step={0.05}
          format={(v) => pct(v, 0)}
          onCommit={(minPop) => update({ minPop })}
        />
        <div className="controls__chips">
          {data && (
            <Chip kind="neutral" title="Calibration map used for this session">
              map: {data.map_id}
            </Chip>
          )}
          {data?.look_ahead && (
            <Chip
              kind="warning"
              icon={'⚠'}
              title="This map was fitted on expirations that include this session's outcome."
            >
              in-sample map: fitted on outcomes after this session
            </Chip>
          )}
          {data?.map_is_identity && (
            <Chip kind="info" icon={'ⓘ'} title="The identity map leaves probabilities unchanged.">
              no calibration (2020 burn-in)
            </Chip>
          )}
        </div>
      </section>

      <OutcomeControls params={params} data={data} onChange={(patch) => update(patch)} />

      {busy && <ErrorState error={busy} variant="banner" />}
      {failure && !busy && <ErrorState error={failure} />}
      {!data && !failure && !busy && <EmptyState title="Loading structures…" />}

      {data && !failure && (
        <>
          <div
            className={refreshing ? 'stats is-refreshing' : 'stats'}
            aria-label="Session figures"
          >
            <StatTile label="Close" unit="$/sh" value={usd(data.underlying_close)} />
            <StatTile label="Forward" unit="$/sh" value={usd(data.forward)} />
            <StatTile
              label="DTE"
              unit="days"
              value={String(data.dte_days)}
              sub={expiryLabel(data.expiration, data.dte_days)}
            />
            <StatTile
              label="P(view)"
              value={pct(data.view.prob)}
              sub={`market ${pct(data.view.prob_market)} · ${signedPoints(data.view.prob - data.view.prob_market)} pts`}
            />
            <StatTile
              label="Tail vols"
              value={`${pct(data.tails.sigma_lo, 0)} / ${pct(data.tails.sigma_hi, 0)}`}
              sub={`lower / upper · mass ${pct(data.tails.mass_lo)} / ${pct(data.tails.mass_hi)}`}
            />
            <StatTile
              label="Structures"
              value={data.n_qualifying.toLocaleString('en-US')}
              sub={`qualifying of ${data.n_structures.toLocaleString('en-US')} scored`}
            />
          </div>

          <section className="card block" aria-label="Return on max loss by price at expiry">
            <div className="block__head">
              <h2>
                Return on max loss at expiry · {data.symbol}{' '}
                {expiryLabel(data.expiration, data.dte_days)}
              </h2>
              <span className="muted">{data.fill === 'mid' ? 'Mid fill' : 'Natural fill'}</span>
            </div>
            {kinds.length === 0 ? (
              <EmptyState
                title="No structure qualifies for this view"
                hint="Lower the P(profit | view) floor or widen the view."
              />
            ) : (
              <Measured minHeight={CHART_HEIGHT}>
                {(width) => (
                  <StructurePayoffChart
                    grid={data.grid}
                    density={data.density}
                    kinds={kinds}
                    selected={selectedKind}
                    view={data.view}
                    close={data.underlying_close}
                    dominance={data.dominance}
                    width={width}
                    height={CHART_HEIGHT}
                    refreshing={refreshing}
                  />
                )}
              </Measured>
            )}
          </section>

          <VerdictCard verdict={data.verdict} kinds={kinds} minPop={params.minPop} />

          <section className="card block" aria-label="Kinds">
            <div className="block__head">
              <h2>Best structure of each kind</h2>
              <span className="muted">
                Qualifying: P(profit | view) ≥ {pct(params.minPop, 0)}; returns per $1 of max loss
              </span>
            </div>
            <KindsTable kinds={kinds} selected={selectedKind} onSelect={select} />
          </section>

          <DetailPanel row={selectedRow} fill={data.fill} ranking={data.ranking} />
        </>
      )}
    </div>
  );
}
