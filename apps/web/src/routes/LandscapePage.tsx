import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  busyError,
  isSessionReady,
  prefetchSession,
  terminalError,
  useChain,
  useDistribution,
  useHeatmap,
  useSessions,
  useUnderlyings,
} from '../api/queries';
import { CdfSmallMultiples } from '../charts/CdfSmallMultiples';
import { heatmapHeight, ProbabilityHeatmap } from '../charts/ProbabilityHeatmap';
import { SessionSparklines } from '../charts/SessionSparklines';
import { SmileChart } from '../charts/SmileChart';
import { xDomainFor } from '../charts/options';
import type { Layout, View, XMode } from '../charts/options';
import { ChainTable } from '../components/ChainTable';
import { Chip } from '../components/Chip';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { Legend } from '../components/Legend';
import type { LegendItem } from '../components/Legend';
import { Measured } from '../components/Measured';
import { Scrubber } from '../components/Scrubber';
import type { Speed } from '../components/Scrubber';
import { SegmentedToggle } from '../components/SegmentedToggle';
import { Select } from '../components/Select';
import { ordColor } from '../lib/colors';
import { expiryLabel, shortDate } from '../lib/format';
import { frameAtOrBefore, strideFrames } from '../lib/sessions';
import type { Stride } from '../lib/sessions';
import type { MapChoice } from '../api/types';
import { DEFAULT_UNDERLYING, useLandscapeParams } from '../state/useLandscapeParams';
import { BASE_FPS, usePlayback, usePrefersReducedMotion } from '../state/usePlayback';

/** Pixels reserved by each chart block until its width is measured (see `Measured`). */
const CDF_MIN_HEIGHT = 340;
const SMILE_HEIGHT = 260;
const SPARKLINES_HEIGHT = 56;

const MAP_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'production', label: 'Production' },
  { value: 'walk_forward', label: 'Walk-forward' },
] as const;
const VIEW_OPTIONS = [
  { value: 'raw', label: 'Raw' },
  { value: 'calibrated', label: 'Calibrated' },
  { value: 'both', label: 'Both' },
] as const;
const LAYOUT_OPTIONS = [
  { value: 'multiples', label: 'Small multiples' },
  { value: 'overlay', label: 'Overlay' },
] as const;
const X_OPTIONS = [
  { value: 'moneyness', label: 'Moneyness' },
  { value: 'strike', label: 'Strike $' },
] as const;

export default function LandscapePage() {
  const client = useQueryClient();
  const [search] = useSearchParams();
  const symbol = search.get('u') ?? DEFAULT_UNDERLYING;

  const underlyings = useUnderlyings();
  const sessionsQuery = useSessions(symbol);
  // keepPreviousData can hand back the previous underlying's list for a moment; ignore it.
  const sessions = sessionsQuery.data?.symbol === symbol ? sessionsQuery.data.sessions : undefined;
  const dates = useMemo(() => sessions?.map((s) => s.session), [sessions]);

  const { params, update } = useLandscapeParams(dates);
  const { map, view, layout, x: xMode } = params;

  const [stride, setStride] = useState<Stride>('every');
  const [speed, setSpeed] = useState<Speed>(1);
  const [live, setLive] = useState<number | null>(null);
  const reduced = usePrefersReducedMotion();
  const maxSpeed: Speed = reduced ? 1 : 4;
  const effectiveSpeed = Math.min(speed, maxSpeed);

  const frames = useMemo(() => strideFrames(dates ?? [], stride), [dates, stride]);
  const shownIndex = live ?? params.index;
  const shownDate = dates && shownIndex >= 0 ? (dates[shownIndex] ?? null) : null;

  const distribution = useDistribution(symbol, shownDate, map);
  const heatmap = useHeatmap(symbol, shownDate, map);
  const chain = useChain(symbol, shownDate);

  // Playback state: the index lives in component state while playing and goes to the URL on pause.
  const isReady = useCallback(
    (frame: number) => {
      const date = dates?.[frames[frame] ?? -1];
      return date !== undefined && isSessionReady(client, symbol, date, map);
    },
    [client, dates, frames, symbol, map],
  );
  const prefetch = useCallback(
    (frame: number) => {
      const date = dates?.[frames[frame] ?? -1];
      if (date !== undefined) prefetchSession(client, symbol, date, map);
    },
    [client, dates, frames, symbol, map],
  );
  const setFrame = useCallback((frame: number) => setLive(frames[frame] ?? null), [frames]);
  const playback = usePlayback({
    length: frames.length,
    index: frameAtOrBefore(frames, shownIndex),
    setIndex: setFrame,
    fps: BASE_FPS * effectiveSpeed,
    stride: 1,
    isReady,
    prefetch,
  });

  const wasPlaying = useRef(false);
  useEffect(() => {
    if (wasPlaying.current && !playback.playing && live !== null) {
      const date = dates?.[live];
      if (date) update({ d: date }, { replace: true });
      setLive(null);
    }
    wasPlaying.current = playback.playing;
  }, [playback.playing, live, dates, update]);

  // A different underlying or map invalidates the frames being played.
  const { pause } = playback;
  useEffect(() => {
    pause();
  }, [symbol, map, pause]);

  const seek = (index: number) => {
    const clamped = Math.min((dates?.length ?? 1) - 1, Math.max(0, index));
    if (playback.playing) setLive(clamped);
    else {
      const date = dates?.[clamped];
      if (date) update({ d: date }, { replace: true });
    }
  };
  const onToggle = () => {
    if (!playback.playing) setLive(shownIndex);
    playback.toggle();
  };

  const busy = busyError(sessionsQuery, distribution, heatmap, chain);
  const failure = terminalError(sessionsQuery, distribution, heatmap, chain);
  const refreshing =
    distribution.isPlaceholderData || heatmap.isPlaceholderData || chain.isPlaceholderData;

  const symbols = underlyings.data?.underlyings.map((u) => u.symbol) ?? [];
  const symbolOptions = (symbols.includes(symbol) ? symbols : [symbol, ...symbols]).map((s) => ({
    value: s,
    label: s,
  }));

  const dist = distribution.data;
  const chainData = chain.data;
  const chainExpiries = chainData?.expirations ?? [];
  const chainExpiry =
    chainExpiries.find((e) => e.expiration === params.exp) ?? chainExpiries[0] ?? null;

  const xDomain = useMemo(() => xDomainFor(dist?.expirations ?? [], xMode as XMode), [dist, xMode]);
  const heatmapVariant = view === 'raw' ? 'raw' : 'calibrated';

  const legend: LegendItem[] = [
    ...(dist?.expirations ?? []).slice(0, 4).map((e, i) => ({
      label: expiryLabel(e.expiration, e.dte_days),
      color: ordColor(i),
    })),
    ...(view === 'both'
      ? [{ label: 'Raw (before calibration)', color: 'var(--raw)', mark: 'dash' as const }]
      : []),
  ];

  return (
    <div className="page">
      <section className="controls" aria-label="Landscape controls">
        <Select
          label="Underlying"
          value={symbol}
          options={symbolOptions}
          onChange={(u) => update({ u })}
        />
        <SegmentedToggle<MapChoice>
          label="Calibration map"
          value={map}
          options={MAP_OPTIONS}
          onChange={(value) => update({ map: value })}
        />
        <SegmentedToggle<View>
          label="Curve"
          value={view}
          options={VIEW_OPTIONS}
          onChange={(value) => update({ view: value })}
        />
        <SegmentedToggle<Layout>
          label="Layout"
          value={layout}
          options={LAYOUT_OPTIONS}
          onChange={(value) => update({ layout: value })}
        />
        <SegmentedToggle<XMode>
          label="X axis"
          value={xMode}
          options={X_OPTIONS}
          onChange={(value) => update({ x: value })}
        />
        <div className="controls__chips">
          {dist && (
            <Chip kind="neutral" title="Calibration map used for this session">
              map: {dist.map_id}
            </Chip>
          )}
          {dist?.look_ahead && (
            <Chip
              kind="warning"
              icon={'⚠'}
              title="This map was fitted on expirations that include this session's outcome."
            >
              in-sample map: fitted on outcomes after this session
            </Chip>
          )}
          {dist?.map_is_identity && (
            <Chip kind="info" icon={'ⓘ'} title="The identity map leaves probabilities unchanged.">
              no calibration (2020 burn-in)
            </Chip>
          )}
        </div>
      </section>

      {busy && <ErrorState error={busy} variant="banner" />}
      {failure && !busy && <ErrorState error={failure} />}

      {!failure && (!dist || !dates) && !busy && <EmptyState title="Loading session…" />}

      {dates && dates.length > 0 && sessions && (
        <section className="card playbar" aria-label="Session scrubber">
          <div className="playbar__context">
            <Measured minHeight={SPARKLINES_HEIGHT}>
              {(width) => (
                <SessionSparklines
                  sessions={sessions}
                  index={Math.max(0, shownIndex)}
                  width={width}
                  onSeek={seek}
                />
              )}
            </Measured>
          </div>
          <Scrubber
            dates={dates}
            index={Math.max(0, shownIndex)}
            onSeek={seek}
            playing={playback.playing}
            atEnd={playback.atEnd}
            onToggle={onToggle}
            onStep={(delta) => seek(shownIndex + delta)}
            speed={effectiveSpeed as Speed}
            onSpeed={setSpeed}
            maxSpeed={maxSpeed}
            stride={stride}
            onStride={setStride}
          />
        </section>
      )}

      {dist && (
        <section className="block" aria-label="Implied CDF and density">
          <div className="block__head">
            <h2>Implied CDF and density</h2>
            <Legend items={legend} />
          </div>
          <Measured minHeight={CDF_MIN_HEIGHT}>
            {(width) => (
              <CdfSmallMultiples
                data={dist}
                view={view}
                layout={layout}
                xMode={xMode}
                width={width}
                refreshing={refreshing}
              />
            )}
          </Measured>
        </section>
      )}

      {heatmap.data && (
        <section className="card block" aria-label="Probability heatmap">
          <div className="block__head">
            <h2>P(S&lt;K) by moneyness</h2>
            <span className="muted">
              {heatmapVariant === 'raw' ? 'Raw' : 'Calibrated'} · {shortDate(heatmap.data.session)}
            </span>
          </div>
          <Measured minHeight={heatmapHeight(heatmap.data.rows.length)}>
            {(width) => (
              <ProbabilityHeatmap
                data={heatmap.data}
                variant={heatmapVariant}
                width={width}
                height={heatmapHeight(heatmap.data.rows.length)}
                refreshing={refreshing}
              />
            )}
          </Measured>
        </section>
      )}

      {chainData && (
        <section className="card block" aria-label="Implied volatility smile">
          <div className="block__head">
            <h2>Implied volatility smile</h2>
            <span className="muted">Out-of-the-money quotes</span>
          </div>
          <Measured minHeight={SMILE_HEIGHT}>
            {(width) => (
              <SmileChart
                expiries={chainData.expirations}
                close={chainData.underlying_close}
                xMode={xMode}
                xDomain={xDomain}
                width={width}
                height={SMILE_HEIGHT}
                refreshing={refreshing}
              />
            )}
          </Measured>
        </section>
      )}

      {chainData && chainExpiry && (
        <section
          className={refreshing ? 'card block is-refreshing' : 'card block'}
          aria-label="Option chain"
        >
          <div className="block__head">
            <h2>Chain</h2>
            <SegmentedToggle
              label="Expiration"
              value={chainExpiry.expiration}
              options={chainExpiries.map((e) => ({
                value: e.expiration,
                label: expiryLabel(e.expiration, e.dte_days),
              }))}
              onChange={(value) => update({ exp: value }, { replace: true })}
            />
          </div>
          <ChainTable expiry={chainExpiry} close={chainData.underlying_close} />
        </section>
      )}
    </div>
  );
}
