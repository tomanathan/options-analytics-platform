import { busyError, terminalError, useOutcomeMap, useSessions } from '../api/queries';
import type { Fill, MapChoice } from '../api/types';
import { OutcomeMatrix } from '../charts/OutcomeMatrix';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { NumberField, SliderField } from '../components/FilterFields';
import { SegmentedToggle } from '../components/SegmentedToggle';
import { Select } from '../components/Select';
import { longDate, pct } from '../lib/format';
import { DEFAULT_UNDERLYING } from '../state/useLandscapeParams';
import { MAX_TARGET_DTE, MIN_TARGET_DTE, useOutcomeParams } from '../state/useOutcomeParams';
import { MAX_MIN_POP } from '../state/useStructureParams';

const FILL_OPTIONS = [
  { value: 'natural', label: 'Natural' },
  { value: 'mid', label: 'Mid' },
] as const;
const MAP_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'production', label: 'Production' },
  { value: 'walk_forward', label: 'Walk-forward' },
] as const;

/** Every ticker against the six preset outcomes: where spreads serve a view better than singles. */
export default function OutcomesPage() {
  const { params, query, update } = useOutcomeParams();
  // The session calendar is the default underlying's; every ticker trades on the same days.
  const sessionsQuery = useSessions(DEFAULT_UNDERLYING);
  const outcome = useOutcomeMap(query);
  const data = outcome.data;

  const busy = busyError(outcome);
  const failure = terminalError(outcome);
  const dates = sessionsQuery.data?.sessions.map((s) => s.session) ?? [];
  const sessionOptions = [
    { value: 'latest', label: 'Latest' },
    ...[...dates].reverse().map((d) => ({ value: d, label: longDate(d) })),
  ];
  if (params.session !== 'latest' && !dates.includes(params.session)) {
    sessionOptions.splice(1, 0, { value: params.session, label: longDate(params.session) });
  }

  return (
    <div className="page">
      <section className="controls" aria-label="Outcome map controls">
        <Select
          label="Session"
          value={params.session}
          options={sessionOptions}
          onChange={(session) => update({ session })}
        />
        <NumberField
          label="Target DTE (days)"
          value={params.targetDte}
          step={1}
          min={MIN_TARGET_DTE}
          onCommit={(value) =>
            update({
              targetDte: Math.round(
                Math.min(MAX_TARGET_DTE, Math.max(MIN_TARGET_DTE, value ?? params.targetDte)),
              ),
            })
          }
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
      </section>

      {busy && <ErrorState error={busy} variant="banner" />}
      {failure && !busy && <ErrorState error={failure} />}
      {!data && !failure && !busy && <EmptyState title="Loading the outcome map…" />}

      {data && !failure && (
        <section className="card block" aria-label="Outcome map">
          <div className="block__head">
            <h2>Which kind serves each outcome</h2>
            <span className="muted">Cell: best kind and its return on max loss if right</span>
          </div>
          {data.rows.length === 0 ? (
            <EmptyState title="No underlying has this session" />
          ) : (
            <OutcomeMatrix
              data={data}
              fill={params.fill}
              map={params.map}
              minPop={params.minPop}
              refreshing={outcome.isPlaceholderData}
            />
          )}
          <p className="card__note" data-testid="outcome-footer">
            Session {longDate(data.session)} · expiration nearest {data.target_dte} days (at least{' '}
            {MIN_TARGET_DTE}) · {data.fill === 'mid' ? 'mid' : 'natural'} fill · map {data.map_id} ·
            qualifying at P(profit | view) ≥ {pct(params.minPop, 0)}
          </p>
        </section>
      )}
    </div>
  );
}
