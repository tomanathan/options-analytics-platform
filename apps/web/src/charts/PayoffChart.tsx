import { useId, useMemo, useState } from 'react';
import type { PointerEvent } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { curveLinear } from '@visx/curve';
import { localPoint } from '@visx/event';
import { GridRows } from '@visx/grid';
import { scaleLinear } from '@visx/scale';
import { AreaClosed, LinePath } from '@visx/shape';
import type { SpreadDetail } from '../api/types';
import { axisNumber, density as fmtDensity, pct, strike, usd } from '../lib/format';
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

const GAP = 22;

interface Step {
  x: number;
  y: number;
}

/**
 * Densities are given at interval midpoints. Interval edges are the midpoints between
 * neighbours, with the outer edges at the knot range, so each flat step covers its interval.
 */
export function densitySteps(
  mid: readonly number[],
  values: readonly number[],
  range: readonly [number, number],
): Step[] {
  const steps: Step[] = [];
  mid.forEach((m, i) => {
    const value = values[i];
    if (value === undefined) return;
    const prev = mid[i - 1];
    const next = mid[i + 1];
    const left = prev === undefined ? range[0] : (prev + m) / 2;
    const right = next === undefined ? range[1] : (m + next) / 2;
    steps.push({ x: left, y: value }, { x: right, y: value });
  });
  return steps;
}

interface PayoffChartProps {
  detail: SpreadDetail;
  width: number;
  height: number;
}

function payoffAt(detail: SpreadDetail, price: number): number | null {
  const exact = detail.payoff.find((p) => Math.abs(p.price - price) < 1e-9);
  if (exact) return exact.payoff;
  const i = nearestIndex(
    detail.payoff.map((p) => p.price),
    price,
  );
  return detail.payoff[i]?.payoff ?? null;
}

/** Payoff at expiry over the implied density: where the money is made and lost. */
export function PayoffChart({ detail, width, height }: PayoffChartProps) {
  const clipId = `clip-${useId().replace(/:/g, '')}`;
  const [hover, setHover] = useState<{ xPx: number; top: number } | null>(null);
  const margin: Margin = { top: 16, right: 16, bottom: 28, left: 52 };
  const { w, h } = plotArea(width, height, margin);
  const topH = (h - GAP) * 0.55;
  const botH = h - GAP - topH;
  const botTop = topH + GAP;

  const prices = detail.payoff.map((p) => p.price);
  const lo = prices[0] ?? 0;
  const hi = prices[prices.length - 1] ?? 1;

  const xScale = useMemo(() => scaleLinear({ domain: [lo, hi], range: [0, w] }), [lo, hi, w]);
  const payoffs = detail.payoff.map((p) => p.payoff);
  const yLo = Math.min(0, ...payoffs);
  const yHi = Math.max(0, ...payoffs);
  const yPay = useMemo(
    () => scaleLinear({ domain: [yLo, yHi === yLo ? yLo + 1 : yHi], range: [topH, 0], nice: true }),
    [yLo, yHi, topH],
  );

  const cal = useMemo(
    () => densitySteps(detail.density_mid, detail.density_calibrated, detail.knot_range),
    [detail],
  );
  const raw = useMemo(
    () => densitySteps(detail.density_mid, detail.density_raw, detail.knot_range),
    [detail],
  );
  const densMax = Math.max(1e-12, ...cal.map((p) => p.y), ...raw.map((p) => p.y)) * 1.1;
  const yDens = useMemo(
    () => scaleLinear({ domain: [0, densMax], range: [botH, 0], nice: true }),
    [densMax, botH],
  );

  const breakevenX = xScale(detail.breakeven);
  const loss =
    detail.regions.prob_max_loss.calibrated + detail.regions.prob_partial_loss.calibrated;
  const profit = detail.regions.prob_profit.calibrated;

  const markers = [
    { key: 'long', label: `L ${strike(detail.long_strike)}`, price: detail.long_strike },
    { key: 'short', label: `S ${strike(detail.short_strike)}`, price: detail.short_strike },
    { key: 'breakeven', label: `BE ${detail.breakeven.toFixed(2)}`, price: detail.breakeven },
  ];

  const hoverPrice = hover ? xScale.invert(hover.xPx) : null;
  let tooltip: JSX.Element | null = null;
  if (hover && hoverPrice !== null) {
    const pay = payoffAt(detail, hoverPrice);
    const di = nearestIndex(detail.density_mid, hoverPrice);
    const dCal = detail.density_calibrated[di];
    const dRaw = detail.density_raw[di];
    tooltip = (
      <ChartTooltip
        left={margin.left + hover.xPx}
        top={hover.top}
        containerWidth={width}
        lines={[
          ...(pay === null ? [] : [{ value: usd(pay), label: 'payoff at expiry ($/sh)' }]),
          ...(dCal === undefined
            ? []
            : [
                {
                  value: `${fmtDensity(dCal)} /$`,
                  label: 'density calibrated',
                  color: 'var(--ink-1)',
                },
              ]),
          ...(dRaw === undefined
            ? []
            : [
                {
                  value: `${fmtDensity(dRaw)} /$`,
                  label: 'density raw',
                  color: 'var(--raw)',
                  dashed: true,
                },
              ]),
        ]}
        footer={`S ${usd(hoverPrice)}`}
      />
    );
  }

  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const point = localPoint(event);
    if (!point) return;
    setHover({ xPx: Math.min(w, Math.max(0, point.x - margin.left)), top: point.y });
  };

  const forwardX = detail.forward === null ? null : xScale(detail.forward);
  const closeX = xScale(detail.underlying_close);

  return (
    <ChartFrame
      width={width}
      height={height}
      margin={margin}
      label={`Payoff at expiry and implied density for ${detail.underlying} ${strike(detail.short_strike)}/${strike(detail.long_strike)}`}
      overlay={tooltip}
    >
      <defs>
        <clipPath id={`${clipId}-all`}>
          <rect x={0} y={0} width={w} height={botH} />
        </clipPath>
        <clipPath id={`${clipId}-left`}>
          <rect x={0} y={0} width={Math.max(0, Math.min(w, breakevenX))} height={botH} />
        </clipPath>
        <clipPath id={`${clipId}-right`}>
          <rect
            x={Math.max(0, Math.min(w, breakevenX))}
            y={0}
            width={Math.max(0, w - Math.max(0, Math.min(w, breakevenX)))}
            height={botH}
          />
        </clipPath>
      </defs>

      <GridRows scale={yPay} width={w} numTicks={4} stroke={gridStroke} />
      <AxisLeft
        scale={yPay}
        numTicks={4}
        tickFormat={(v) => usd(Number(v), 2)}
        hideAxisLine
        hideTicks
        tickLabelProps={leftTickLabel}
      />
      <line
        x1={0}
        x2={w}
        y1={yPay(0)}
        y2={yPay(0)}
        stroke="var(--axis)"
        strokeWidth={1}
        data-testid="payoff-zero"
      />
      <LinePath
        data={detail.payoff}
        x={(p) => xScale(p.price)}
        y={(p) => yPay(p.payoff)}
        curve={curveLinear}
        stroke="var(--ink-1)"
        strokeWidth={2}
        strokeLinejoin="round"
        fill="none"
        data-testid="payoff-line"
      />
      {markers.map((m) => {
        const y = payoffAt(detail, m.price);
        if (y === null) return null;
        const x = xScale(m.price);
        // Offsets keep the three labels apart: long to the left, breakeven below the slope,
        // short above its plateau.
        const place =
          m.key === 'long'
            ? { dx: -8, dy: 4, anchor: 'end' as const }
            : m.key === 'short'
              ? { dx: -8, dy: -8, anchor: 'end' as const }
              : { dx: 8, dy: 14, anchor: 'start' as const };
        return (
          <g key={m.key} data-testid={`marker-${m.key}`}>
            <circle
              cx={x}
              cy={yPay(y)}
              r={4}
              fill="var(--ink-1)"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
            <text
              x={x + place.dx}
              y={yPay(y) + place.dy}
              textAnchor={place.anchor}
              fill="var(--ink-2)"
              fontSize={11}
              className="halo"
            >
              {m.label}
            </text>
          </g>
        );
      })}
      <text x={-margin.left + 2} y={-5} fill="var(--ink-muted)" fontSize={10}>
        payoff, $/sh
      </text>

      <g transform={`translate(0 ${botTop})`}>
        <GridRows scale={yDens} width={w} numTicks={2} stroke={gridStroke} />
        <AxisLeft
          scale={yDens}
          numTicks={2}
          tickFormat={(v) => axisNumber(Number(v))}
          hideAxisLine
          hideTicks
          tickLabelProps={leftTickLabel}
        />
        <AxisBottom
          {...axisBase}
          scale={xScale}
          top={botH}
          numTicks={Math.max(3, Math.floor(w / 70))}
          tickFormat={(v) => `$${Math.round(Number(v))}`}
          tickLabelProps={bottomTickLabel}
        />
        <text x={-margin.left + 2} y={-6} fill="var(--ink-muted)" fontSize={10}>
          density, 1/$
        </text>
        {(['left', 'right'] as const).map((side) => (
          <g key={side} clipPath={`url(#${clipId}-${side})`}>
            <AreaClosed
              data={cal}
              x={(d) => xScale(d.x)}
              y={(d) => yDens(d.y)}
              yScale={yDens}
              curve={curveLinear}
              fill={side === 'left' ? 'var(--series-2)' : 'var(--series-1)'}
              fillOpacity={0.3}
              data-testid={`density-${side}`}
            />
          </g>
        ))}
        <g clipPath={`url(#${clipId}-all)`}>
          <LinePath
            data={cal}
            x={(d) => xScale(d.x)}
            y={(d) => yDens(d.y)}
            curve={curveLinear}
            stroke="var(--ink-2)"
            strokeWidth={1.5}
            fill="none"
          />
          <LinePath
            data={raw}
            x={(d) => xScale(d.x)}
            y={(d) => yDens(d.y)}
            curve={curveLinear}
            stroke="var(--raw)"
            strokeWidth={1.5}
            strokeDasharray="5 4"
            fill="none"
            data-testid="density-raw"
          />
        </g>
        <line
          x1={breakevenX}
          x2={breakevenX}
          y1={0}
          y2={botH}
          stroke="var(--ink-1)"
          strokeWidth={1}
        />
        <text
          x={breakevenX - 6}
          y={10}
          textAnchor="end"
          fill="var(--ink-1)"
          fontSize={11}
          className="halo"
        >
          {`P(loss) ${pct(loss)}`}
        </text>
        <text x={breakevenX + 6} y={10} fill="var(--ink-1)" fontSize={11} className="halo">
          {`P(profit) ${pct(profit)}`}
        </text>
        <line
          x1={closeX}
          x2={closeX}
          y1={0}
          y2={botH}
          stroke="var(--ink-2)"
          strokeWidth={1}
          strokeDasharray="1 3"
          strokeLinecap="round"
        />
        <text x={closeX + 4} y={botH - 4} fill="var(--ink-2)" fontSize={11} className="halo">
          S
        </text>
        {forwardX !== null && (
          <>
            <line
              x1={forwardX}
              x2={forwardX}
              y1={0}
              y2={botH}
              stroke="var(--ink-2)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <text x={forwardX + 4} y={botH - 16} fill="var(--ink-2)" fontSize={11} className="halo">
              F
            </text>
          </>
        )}
      </g>

      {hover && (
        <line
          x1={hover.xPx}
          x2={hover.xPx}
          y1={0}
          y2={h}
          stroke="var(--ink-1)"
          strokeWidth={1}
          opacity={0.4}
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
    </ChartFrame>
  );
}
