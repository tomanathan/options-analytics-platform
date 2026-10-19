import { useId, useMemo, useState } from 'react';
import type { PointerEvent } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { curveLinear } from '@visx/curve';
import { localPoint } from '@visx/event';
import { GridRows } from '@visx/grid';
import { scaleLinear } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { ChainExpiry } from '../api/types';
import { ordColor } from '../lib/colors';
import { num, percentPointTick, usd } from '../lib/format';
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
import type { XMode } from './options';

interface SmilePoint {
  x: number;
  /** Implied volatility in percent. */
  iv: number;
  strike: number;
}

interface SmileSeries {
  expiry: ChainExpiry;
  color: string;
  points: SmilePoint[];
}

/** OTM quotes only: puts below the close, calls at or above it, with a positive IV. */
export function smilePoints(expiry: ChainExpiry, close: number | null, mode: XMode): SmilePoint[] {
  if (close === null) return [];
  const points: SmilePoint[] = [];
  for (const quote of expiry.quotes) {
    if (quote.iv === null || !(quote.iv > 0)) continue;
    const otm = quote.strike < close ? quote.option_right === 'P' : quote.option_right === 'C';
    if (!otm) continue;
    const moneyness = quote.moneyness ?? quote.strike / close;
    points.push({
      x: mode === 'moneyness' ? moneyness : quote.strike,
      iv: quote.iv * 100,
      strike: quote.strike,
    });
  }
  return points.sort((a, b) => a.x - b.x);
}

function percentile(values: number[], q: number): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  const i = Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1) + 0.5));
  return sorted[i] ?? 1;
}

interface SmileChartProps {
  expiries: readonly ChainExpiry[];
  close: number | null;
  xMode: XMode;
  xDomain: [number, number];
  width: number;
  height: number;
  refreshing?: boolean;
}

/** Implied-volatility smile per expiry, sharing the x axis of the CDF panels. */
export function SmileChart({
  expiries,
  close,
  xMode,
  xDomain,
  width,
  height,
  refreshing,
}: SmileChartProps) {
  const clipId = `clip-${useId().replace(/:/g, '')}`;
  const [hover, setHover] = useState<{ xPx: number; top: number } | null>(null);
  const margin: Margin = { top: 18, right: 40, bottom: 28, left: 44 };
  const { w, h } = plotArea(width, height, margin);

  const series: SmileSeries[] = useMemo(
    () =>
      expiries.slice(0, 4).map((expiry, index) => ({
        expiry,
        color: ordColor(index),
        points: smilePoints(expiry, close, xMode),
      })),
    [expiries, close, xMode],
  );

  const yMax = useMemo(() => {
    const all = series.flatMap((s) => s.points.map((p) => p.iv));
    const top = percentile(all, 0.99);
    const step = top > 60 ? 20 : top > 25 ? 10 : 5;
    return Math.max(step, Math.ceil(top / step) * step);
  }, [series]);

  const xScale = useMemo(() => scaleLinear({ domain: xDomain, range: [0, w] }), [xDomain, w]);
  const yScale = useMemo(() => scaleLinear({ domain: [0, yMax], range: [h, 0] }), [yMax, h]);

  const hoverValue = hover ? xScale.invert(hover.xPx) : null;
  const picks =
    hoverValue === null
      ? []
      : series.map((s) =>
          nearestIndex(
            s.points.map((p) => p.x),
            hoverValue,
          ),
        );
  const crossPoint = (() => {
    const s0 = series.find((s) => s.points.length > 0);
    if (!s0 || hoverValue === null) return null;
    const i = nearestIndex(
      s0.points.map((p) => p.x),
      hoverValue,
    );
    return s0.points[i] ?? null;
  })();

  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const point = localPoint(event);
    if (!point) return;
    setHover({ xPx: Math.min(w, Math.max(0, point.x - margin.left)), top: point.y });
  };

  let tooltip: JSX.Element | null = null;
  if (hover && crossPoint) {
    tooltip = (
      <ChartTooltip
        left={margin.left + xScale(crossPoint.x)}
        top={hover.top}
        containerWidth={width}
        lines={series.flatMap((s, i) => {
          const p = s.points[picks[i] ?? -1];
          return p
            ? [
                {
                  value: `${p.iv.toFixed(1)}%`,
                  label: `${s.expiry.dte_days}d · K ${usd(p.strike)}`,
                  color: s.color,
                },
              ]
            : [];
        })}
        footer={xMode === 'moneyness' ? `m ${num(crossPoint.x, 3)}` : `K ${usd(crossPoint.x)}`}
      />
    );
  }

  return (
    <ChartFrame
      width={width}
      height={height}
      margin={margin}
      label="Implied volatility smile, out-of-the-money quotes by expiration"
      refreshing={refreshing}
      overlay={tooltip}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={-4} width={w} height={h + 8} />
        </clipPath>
      </defs>
      <GridRows scale={yScale} width={w} numTicks={4} stroke={gridStroke} />
      <AxisLeft
        scale={yScale}
        numTicks={4}
        tickFormat={(v) => percentPointTick(Number(v))}
        hideAxisLine
        hideTicks
        tickLabelProps={leftTickLabel}
      />
      <AxisBottom
        {...axisBase}
        scale={xScale}
        top={h}
        numTicks={Math.max(3, Math.floor(w / 70))}
        tickFormat={(v) =>
          xMode === 'moneyness' ? Number(v).toFixed(2) : `$${Math.round(Number(v))}`
        }
        tickLabelProps={bottomTickLabel}
      />
      <g clipPath={`url(#${clipId})`}>
        {series.map((s) => (
          <g key={s.expiry.expiration}>
            <LinePath
              data={s.points}
              x={(p) => xScale(p.x)}
              y={(p) => yScale(p.iv)}
              curve={curveLinear}
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              fill="none"
              data-testid="smile-line"
            />
            {s.points.map((p) => (
              <circle
                key={p.strike}
                cx={xScale(p.x)}
                cy={yScale(p.iv)}
                r={4}
                fill={s.color}
                stroke="var(--surface-1)"
                strokeWidth={2}
              />
            ))}
          </g>
        ))}
      </g>
      {series.map((s) => {
        const last = s.points[s.points.length - 1];
        if (!last || last.x > xDomain[1]) return null;
        return (
          <text
            key={`label-${s.expiry.expiration}`}
            x={xScale(last.x) + 8}
            y={yScale(last.iv)}
            dy="0.33em"
            fill="var(--ink-2)"
            fontSize={11}
            className="halo"
          >
            {`${s.expiry.dte_days}d`}
          </text>
        );
      })}
      {crossPoint && (
        <line
          x1={xScale(crossPoint.x)}
          x2={xScale(crossPoint.x)}
          y1={0}
          y2={h}
          stroke="var(--ink-1)"
          strokeWidth={1}
          opacity={0.5}
          pointerEvents="none"
        />
      )}
      <rect
        x={0}
        y={0}
        width={w}
        height={h}
        fill="transparent"
        onPointerMove={onPointerMove}
        onPointerLeave={() => setHover(null)}
      />
      <text x={-margin.left + 2} y={-4} fill="var(--ink-muted)" fontSize={10}>
        IV
      </text>
    </ChartFrame>
  );
}
