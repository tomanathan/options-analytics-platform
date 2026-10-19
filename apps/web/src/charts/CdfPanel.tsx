import { useId, useMemo, useState } from 'react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { curveLinear } from '@visx/curve';
import { localPoint } from '@visx/event';
import { GridRows } from '@visx/grid';
import { scaleLinear } from '@visx/scale';
import { AreaClosed, LinePath } from '@visx/shape';
import { Chip } from '../components/Chip';
import type { ExpiryDistribution } from '../api/types';
import {
  axisNumber,
  density as fmtDensity,
  expiryLabel,
  longDate,
  num,
  pct,
  pctTick,
  usd,
} from '../lib/format';
import { orderFlags } from '../lib/flags';
import {
  axisBase,
  bottomTickLabel,
  gridStroke,
  leftTickLabel,
  nearestIndex,
  plotArea,
} from './axes';
import type { Margin } from './axes';
import { ChartFrame } from './ChartFrame';
import { ChartTooltip } from './ChartTooltip';
import type { TooltipLine } from './ChartTooltip';
import { crossingX, curveX, levelX, showsCalibrated, showsRaw } from './options';
import type { PlotSeries, View, XMode } from './options';

const CDF_TICKS = [0, 0.25, 0.5, 0.75, 1];
const GAP = 16;
const DENSITY_SHARE = 0.35;
/** Vertical distance between the median labels of the overlay, so near-equal medians stay legible. */
const MEDIAN_LABEL_STEP = 14;

interface Point {
  x: number;
  y: number;
}

/** Interval densities drawn as steps: one flat segment per strike interval. */
function stepPoints(xs: readonly number[], values: readonly number[], scale: number): Point[] {
  const points: Point[] = [];
  values.forEach((value, i) => {
    const x0 = xs[i];
    const x1 = xs[i + 1];
    if (x0 === undefined || x1 === undefined) return;
    points.push({ x: x0, y: value * scale }, { x: x1, y: value * scale });
  });
  return points;
}

function xTick(mode: XMode) {
  return (value: { valueOf(): number }) =>
    mode === 'moneyness' ? Number(value).toFixed(2) : `$${Math.round(Number(value))}`;
}

interface CdfPlotProps {
  series: readonly PlotSeries[];
  view: View;
  xMode: XMode;
  xDomain: [number, number];
  width: number;
  height: number;
  /** Draw the density plot under the CDF (single-expiry panels only). */
  showDensity: boolean;
  refreshing?: boolean;
  label: string;
}

/** CDF (and optionally density) of one or several expiries on a shared x axis. */
export function CdfPlot({
  series,
  view,
  xMode,
  xDomain,
  width,
  height,
  showDensity,
  refreshing,
  label,
}: CdfPlotProps) {
  const clipId = `clip-${useId().replace(/:/g, '')}`;
  const [hover, setHover] = useState<{ xPx: number; top: number } | null>(null);
  const multi = series.length > 1;
  const margin: Margin = { top: 18, right: 14, bottom: 26, left: 44 };
  const { w, h } = plotArea(width, height, margin);
  const cdfH = showDensity ? (h - GAP) * (1 - DENSITY_SHARE) : h;
  const densH = showDensity ? h - GAP - cdfH : 0;
  const densTop = cdfH + GAP;

  const xScale = useMemo(() => scaleLinear({ domain: xDomain, range: [0, w] }), [xDomain, w]);
  const yCdf = useMemo(() => scaleLinear({ domain: [0, 1], range: [cdfH, 0] }), [cdfH]);

  const first = series[0];
  const close = first?.expiry.underlying_close ?? null;

  const geometry = useMemo(
    () =>
      series.map((item) => {
        const xs = curveX(item.curve, xMode);
        const scale = xMode === 'moneyness' ? (item.expiry.underlying_close ?? 1) : 1;
        return {
          xs,
          cal: item.curve.cdf_calibrated,
          raw: item.curve.raw_cdf,
          densCal: stepPoints(xs, item.curve.density_calibrated, scale),
          densRaw: stepPoints(xs, item.curve.density, scale),
        };
      }),
    [series, xMode],
  );

  const densityMax = useMemo(() => {
    let max = 0;
    geometry.forEach((g) => {
      const pts = [
        ...(showsCalibrated(view) ? g.densCal : []),
        ...(showsRaw(view) ? g.densRaw : []),
      ];
      pts.forEach((p) => {
        if (p.y > max) max = p.y;
      });
    });
    return max > 0 ? max * 1.08 : 1;
  }, [geometry, view]);
  const yDens = useMemo(
    () => scaleLinear({ domain: [0, densityMax], range: [densH, 0], nice: true }),
    [densityMax, densH],
  );

  const hoverValue = hover ? xScale.invert(hover.xPx) : null;
  const hoverIdx = hoverValue === null ? [] : geometry.map((g) => nearestIndex(g.xs, hoverValue));
  const crossX = (() => {
    const g0 = geometry[0];
    const i0 = hoverIdx[0];
    if (!g0 || i0 === undefined || i0 < 0) return null;
    const x = g0.xs[i0];
    return x === undefined ? null : xScale(x);
  })();

  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const point = localPoint(event);
    if (!point) return;
    setHover({
      xPx: Math.min(w, Math.max(0, point.x - margin.left)),
      top: point.y,
    });
  };

  const onKeyDown = (event: KeyboardEvent<SVGRectElement>) => {
    const g0 = geometry[0];
    if (!g0 || (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight')) return;
    event.preventDefault();
    const current = hoverIdx[0] ?? nearestIndex(g0.xs, xDomain[0]);
    const next = Math.min(
      g0.xs.length - 1,
      Math.max(0, current + (event.key === 'ArrowRight' ? 1 : -1)),
    );
    const x = g0.xs[next];
    if (x !== undefined) setHover({ xPx: xScale(x), top: margin.top + cdfH / 2 });
  };

  let tooltip: JSX.Element | null = null;
  if (hover && hoverValue !== null && crossX !== null) {
    const lines: TooltipLine[] = [];
    let footer = '';
    series.forEach((item, s) => {
      const i = hoverIdx[s];
      if (i === undefined || i < 0) return;
      const tag = multi ? `${item.expiry.dte_days}d` : undefined;
      if (showsCalibrated(view)) {
        lines.push({
          value: pct(item.curve.cdf_calibrated[i]),
          label: tag ? `${tag} calibrated` : 'P(S<K) calibrated',
          color: item.color,
        });
      }
      if (showsRaw(view)) {
        lines.push({
          value: pct(item.curve.raw_cdf[i]),
          label: tag ? `${tag} raw` : 'P(S<K) raw',
          color: 'var(--raw)',
          dashed: true,
        });
      }
      if (!multi) {
        const d =
          item.curve.density_calibrated[Math.min(i, item.curve.density_calibrated.length - 1)];
        if (d !== undefined) lines.push({ value: `${fmtDensity(d)} /$`, label: 'density' });
        footer = `K ${usd(item.curve.knots[i])} · m ${num(item.curve.moneyness[i], 3)} · ${expiryLabel(item.expiry.expiration, item.expiry.dte_days)}`;
      }
    });
    if (multi)
      footer = xMode === 'moneyness' ? `m ${hoverValue.toFixed(3)}` : `K ${usd(hoverValue)}`;
    tooltip = (
      <ChartTooltip
        left={hover.xPx + margin.left}
        top={hover.top}
        containerWidth={width}
        lines={lines}
        footer={footer}
      />
    );
  }

  const forwardX = first ? levelX(first.expiry.forward ?? NaN, close, xMode) : null;
  const closeX = first && close !== null ? levelX(close, close, xMode) : null;
  const settle = first?.expiry;
  const settleX =
    settle && settle.settlement_close !== null
      ? levelX(settle.settlement_close, close, xMode)
      : null;
  const settleP = settle
    ? view === 'raw'
      ? settle.prob_below_settlement
      : settle.prob_below_settlement_calibrated
    : null;
  const inDomain = (x: number | null): x is number =>
    x !== null && Number.isFinite(x) && x >= xDomain[0] && x <= xDomain[1];

  const labelFlip = (x: number) => x > w * 0.6;

  return (
    <ChartFrame
      width={width}
      height={height}
      margin={margin}
      label={label}
      refreshing={refreshing}
      overlay={tooltip}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={-2} width={w} height={h + 4} />
        </clipPath>
      </defs>

      <GridRows scale={yCdf} width={w} tickValues={CDF_TICKS} stroke={gridStroke} />
      <AxisLeft
        scale={yCdf}
        tickValues={CDF_TICKS}
        tickFormat={(v) => pctTick(Number(v))}
        hideAxisLine
        hideTicks
        tickLabelProps={leftTickLabel}
      />
      {showDensity && (
        <g transform={`translate(0 ${densTop})`}>
          <GridRows scale={yDens} width={w} numTicks={2} stroke={gridStroke} />
          <AxisLeft
            scale={yDens}
            numTicks={2}
            tickFormat={(v) => axisNumber(Number(v))}
            hideAxisLine
            hideTicks
            tickLabelProps={leftTickLabel}
          />
          <text x={0} y={-5} fill="var(--ink-muted)" fontSize={10}>
            density
          </text>
        </g>
      )}
      <AxisBottom
        {...axisBase}
        scale={xScale}
        top={showDensity ? densTop + densH : cdfH}
        numTicks={Math.max(3, Math.floor(w / 70))}
        tickFormat={xTick(xMode)}
        tickLabelProps={bottomTickLabel}
      />

      <g clipPath={`url(#${clipId})`}>
        {geometry.map((g, s) => {
          const item = series[s];
          if (!item) return null;
          const rawSolid = view === 'raw';
          return (
            <g key={item.expiry.expiration}>
              {showsRaw(view) && (
                <LinePath
                  data={g.xs.map((x, i) => ({ x, y: g.raw[i] ?? NaN }))}
                  x={(d) => xScale(d.x)}
                  y={(d) => yCdf(d.y)}
                  curve={curveLinear}
                  defined={(d) => Number.isFinite(d.y)}
                  stroke={rawSolid ? item.color : 'var(--raw)'}
                  strokeWidth={rawSolid ? 2 : 1.5}
                  strokeDasharray={rawSolid ? undefined : '5 4'}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  fill="none"
                  data-testid="cdf-raw"
                />
              )}
              {showsCalibrated(view) && (
                <LinePath
                  data={g.xs.map((x, i) => ({ x, y: g.cal[i] ?? NaN }))}
                  x={(d) => xScale(d.x)}
                  y={(d) => yCdf(d.y)}
                  curve={curveLinear}
                  defined={(d) => Number.isFinite(d.y)}
                  stroke={item.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  fill="none"
                  data-testid="cdf-calibrated"
                />
              )}
              {showDensity && (
                <g transform={`translate(0 ${densTop})`}>
                  {showsCalibrated(view) ? (
                    <>
                      <AreaClosed
                        data={g.densCal}
                        x={(d) => xScale(d.x)}
                        y={(d) => yDens(d.y)}
                        yScale={yDens}
                        curve={curveLinear}
                        fill={item.color}
                        fillOpacity={0.25}
                      />
                      <LinePath
                        data={g.densCal}
                        x={(d) => xScale(d.x)}
                        y={(d) => yDens(d.y)}
                        curve={curveLinear}
                        stroke={item.color}
                        strokeWidth={2}
                        fill="none"
                      />
                    </>
                  ) : null}
                  {showsRaw(view) && (
                    <LinePath
                      data={g.densRaw}
                      x={(d) => xScale(d.x)}
                      y={(d) => yDens(d.y)}
                      curve={curveLinear}
                      stroke={showsCalibrated(view) ? 'var(--raw)' : item.color}
                      strokeWidth={showsCalibrated(view) ? 1.5 : 2}
                      strokeDasharray={showsCalibrated(view) ? '5 4' : undefined}
                      fill="none"
                    />
                  )}
                </g>
              )}
            </g>
          );
        })}
      </g>

      {!multi && inDomain(forwardX) && first && (
        <g>
          <line
            x1={xScale(forwardX)}
            x2={xScale(forwardX)}
            y1={0}
            y2={showDensity ? densTop + densH : cdfH}
            stroke="var(--ink-2)"
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <text
            x={xScale(forwardX) + (labelFlip(xScale(forwardX)) ? -4 : 4)}
            y={-5}
            fill="var(--ink-2)"
            fontSize={11}
            className="halo"
            textAnchor={labelFlip(xScale(forwardX)) ? 'end' : 'start'}
          >
            {`F ${num(first.expiry.forward, 2)}`}
          </text>
        </g>
      )}
      {inDomain(closeX) && (
        <g>
          <line
            x1={xScale(closeX)}
            x2={xScale(closeX)}
            y1={0}
            y2={showDensity ? densTop + densH : cdfH}
            stroke="var(--ink-2)"
            strokeWidth={1}
            strokeDasharray="1 3"
            strokeLinecap="round"
          />
          <text
            x={xScale(closeX) + (labelFlip(xScale(closeX)) ? -4 : 4)}
            y={cdfH - 5}
            fill="var(--ink-2)"
            fontSize={11}
            className="halo"
            textAnchor={labelFlip(xScale(closeX)) ? 'end' : 'start'}
          >
            S
          </text>
        </g>
      )}

      {!multi && inDomain(settleX) && settleP !== null && settle && (
        <g data-testid="settlement-marker">
          <path
            d={`M${xScale(settleX)} ${yCdf(settleP) - 6}L${xScale(settleX) + 6} ${yCdf(settleP)}L${xScale(settleX)} ${yCdf(settleP) + 6}L${xScale(settleX) - 6} ${yCdf(settleP)}Z`}
            fill="var(--ink-1)"
            stroke="var(--surface-1)"
            strokeWidth={2}
          />
          <text
            x={xScale(settleX) + (labelFlip(xScale(settleX)) ? -10 : 10)}
            y={yCdf(settleP) + (settleP > 0.8 ? 16 : -8)}
            fill="var(--ink-1)"
            fontSize={11}
            className="halo"
            textAnchor={labelFlip(xScale(settleX)) ? 'end' : 'start'}
          >
            {`settled ${usd(settle.settlement_close)} · P=${num(settleP, 2)}`}
          </text>
        </g>
      )}

      {multi &&
        geometry.map((g, s) => {
          const item = series[s];
          if (!item) return null;
          const values = showsCalibrated(view) ? g.cal : g.raw;
          const x = crossingX(g.xs, values, 0.5);
          if (x === null || !inDomain(x)) return null;
          return (
            <g key={`label-${item.expiry.expiration}`}>
              <circle
                cx={xScale(x)}
                cy={yCdf(0.5)}
                r={4}
                fill={item.color}
                stroke="var(--surface-1)"
                strokeWidth={2}
              />
              <text
                x={xScale(x) - 7}
                y={yCdf(0.5) - 8 - s * MEDIAN_LABEL_STEP}
                fill="var(--ink-1)"
                fontSize={11}
                className="halo"
                textAnchor="end"
              >
                {`${item.expiry.dte_days}d`}
              </text>
            </g>
          );
        })}

      {crossX !== null && (
        <g pointerEvents="none">
          <line
            x1={crossX}
            x2={crossX}
            y1={0}
            y2={showDensity ? densTop + densH : cdfH}
            stroke="var(--ink-1)"
            strokeWidth={1}
            opacity={0.5}
          />
          {geometry.map((g, s) => {
            const item = series[s];
            const i = hoverIdx[s];
            if (!item || i === undefined || i < 0) return null;
            const x = g.xs[i];
            const y = showsCalibrated(view) ? g.cal[i] : g.raw[i];
            if (x === undefined || y === undefined) return null;
            return (
              <circle
                key={item.expiry.expiration}
                cx={xScale(x)}
                cy={yCdf(y)}
                r={4}
                fill={item.color}
                stroke="var(--surface-1)"
                strokeWidth={2}
              />
            );
          })}
        </g>
      )}

      <rect
        x={0}
        y={0}
        width={w}
        height={h}
        fill="transparent"
        tabIndex={0}
        aria-label="Probability curve. Use the left and right arrow keys to inspect strikes."
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={onKeyDown}
        style={{ outline: 'none' }}
      />
      <text x={-margin.left + 2} y={-5} fill="var(--ink-muted)" fontSize={10}>
        P(S&lt;K)
      </text>
    </ChartFrame>
  );
}

interface CdfPanelProps {
  /** The expiry for this slot, or null for an empty slot. */
  expiry: ExpiryDistribution | null;
  color: string;
  view: View;
  xMode: XMode;
  xDomain: [number, number];
  width: number;
  height: number;
  refreshing?: boolean;
}

/** One expiry: header with flag chips, then CDF over density on a shared x axis. */
export function CdfPanel({
  expiry,
  color,
  view,
  xMode,
  xDomain,
  width,
  height,
  refreshing,
}: CdfPanelProps) {
  if (!expiry) {
    return (
      <section className="card cdf-panel cdf-panel--empty" style={{ minHeight: height }}>
        <p className="empty__title">No expiration in this slot</p>
      </section>
    );
  }
  const title = expiryLabel(expiry.expiration, expiry.dte_days);
  const flags = orderFlags(expiry.flags);
  return (
    <section className="card cdf-panel" aria-label={`Distribution for ${title}`}>
      <header className="card__header">
        <h3 className="card__title">{title}</h3>
        <div className="chips">
          {expiry.short_dated && (
            <Chip kind="info" icon={'ⓘ'} title="Fewer days to expiry than the scoring minimum.">
              short-dated
            </Chip>
          )}
          {flags.map((flag) => (
            <Chip key={flag.flag} kind={flag.kind} icon={flag.icon} title={flag.meaning}>
              {flag.label}
            </Chip>
          ))}
        </div>
      </header>
      {expiry.curve ? (
        <CdfPlot
          series={[{ expiry, curve: expiry.curve, color }]}
          view={view}
          xMode={xMode}
          xDomain={xDomain}
          width={width}
          height={height}
          showDensity
          refreshing={refreshing}
          label={`Implied CDF and density for ${title}`}
        />
      ) : (
        <div className="empty" style={{ height }}>
          <p className="empty__title">No curve for this expiration</p>
          <p className="empty__hint">{expiry.unavailable_reason ?? 'unavailable'}</p>
        </div>
      )}
      {expiry.settlement_date && (
        <p className="card__note">
          Settled {longDate(expiry.settlement_date)} at {usd(expiry.settlement_close)}
        </p>
      )}
    </section>
  );
}

interface CdfOverlayProps {
  series: readonly PlotSeries[];
  view: View;
  xMode: XMode;
  xDomain: [number, number];
  width: number;
  height: number;
  refreshing?: boolean;
}

/** All expiries on one CDF plot, each labelled at its interpolated median (F = 0.5), stacked by series. */
export function CdfOverlay({
  series,
  view,
  xMode,
  xDomain,
  width,
  height,
  refreshing,
}: CdfOverlayProps) {
  return (
    <section className="card cdf-panel" aria-label="Distribution overlay">
      <header className="card__header">
        <h3 className="card__title">All expirations</h3>
      </header>
      {series.length > 0 ? (
        <CdfPlot
          series={series}
          view={view}
          xMode={xMode}
          xDomain={xDomain}
          width={width}
          height={height}
          showDensity={false}
          refreshing={refreshing}
          label="Implied CDFs of every expiration overlaid"
        />
      ) : (
        <div className="empty" style={{ height }}>
          <p className="empty__title">No curves for this session</p>
        </div>
      )}
    </section>
  );
}
