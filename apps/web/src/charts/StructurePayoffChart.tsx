import { useId, useMemo, useState } from 'react';
import type { PointerEvent } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { curveLinear } from '@visx/curve';
import { localPoint } from '@visx/event';
import { GridRows } from '@visx/grid';
import { scaleLinear } from '@visx/scale';
import { AreaClosed, LinePath } from '@visx/shape';
import type { DominanceSegment, StructureKind, StructureKindBest } from '../api/types';
import { Legend } from '../components/Legend';
import type { LegendItem } from '../components/Legend';
import { multiple, usd } from '../lib/format';
import { DIRECTION_GLYPH, kindDash, KINDS } from '../lib/structures';
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

/** The y axis never reaches past this many multiples of max loss. */
export const Y_CAP = 4;
const Y_FLOOR = -1;
/** Smallest top of the y axis, so a flat set of curves still has room above zero. */
const Y_MIN_TOP = 0.5;
const STRIP_HEIGHT = 12;
const STRIP_GAP = 30;
/** The density area fills at most this share of the plot height. */
const DENSITY_SHARE = 0.55;

export interface ViewBounds {
  lo: number | null;
  hi: number | null;
  outside: boolean;
}

interface StructurePayoffChartProps {
  /** Terminal prices, $/sh, ascending. */
  grid: readonly number[];
  /** Calibrated density at each grid price, 1/$. */
  density: readonly number[];
  kinds: readonly StructureKindBest[];
  selected: StructureKind | null;
  view: ViewBounds;
  close: number;
  dominance: readonly DominanceSegment[];
  width: number;
  height: number;
  refreshing?: boolean;
}

/** The value below which `share` of `values` lie (nearest rank); NaN for an empty list. */
export function quantile(values: readonly number[], share: number): number {
  const finite = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (finite.length === 0) return Number.NaN;
  const index = Math.min(finite.length - 1, Math.max(0, Math.ceil(share * finite.length) - 1));
  return finite[index] ?? Number.NaN;
}

/**
 * Top of the y axis: the largest 95th-percentile curve value over the kinds, capped at
 * `Y_CAP` and never below `Y_MIN_TOP`.
 */
export function yTop(kinds: readonly StructureKindBest[]): number {
  const p95 = kinds.map((kind) => quantile(kind.curve, 0.95)).filter(Number.isFinite);
  const top = p95.length === 0 ? Y_MIN_TOP : Math.max(...p95);
  return Math.max(Y_MIN_TOP, Math.min(Y_CAP, top));
}

/** Shaded x ranges of a view: one band inside, or the two sides of an outside view. */
export function viewBands(view: ViewBounds, domain: readonly [number, number]): [number, number][] {
  const [lo, hi] = domain;
  const a = view.lo === null ? lo : Math.min(hi, Math.max(lo, view.lo));
  const b = view.hi === null ? hi : Math.min(hi, Math.max(lo, view.hi));
  const bands: [number, number][] = view.outside
    ? [
        [lo, view.lo === null ? lo : a],
        [view.hi === null ? hi : b, hi],
      ]
    : [[a, b]];
  return bands.filter(([from, to]) => to > from);
}

interface Hover {
  index: number;
  xPx: number;
  top: number;
}

/**
 * Return on max loss at expiry of the best structure of each kind over the terminal price, with
 * the calibrated density underneath, the view shaded and a strip of the winning kind per price.
 */
export function StructurePayoffChart({
  grid,
  density,
  kinds,
  selected,
  view,
  close,
  dominance,
  width,
  height,
  refreshing,
}: StructurePayoffChartProps) {
  const clipId = `clip-${useId().replace(/:/g, '')}`;
  const [hover, setHover] = useState<Hover | null>(null);
  const margin: Margin = { top: 18, right: 16, bottom: STRIP_GAP + STRIP_HEIGHT + 4, left: 52 };
  const { w, h } = plotArea(width, height, margin);

  const lo = grid[0] ?? 0;
  const hi = grid[grid.length - 1] ?? 1;
  const xScale = useMemo(() => scaleLinear({ domain: [lo, hi], range: [0, w] }), [lo, hi, w]);
  const top = useMemo(() => yTop(kinds), [kinds]);
  const yScale = useMemo(() => scaleLinear({ domain: [Y_FLOOR, top], range: [h, 0] }), [top, h]);
  const densMax = Math.max(1e-12, ...density.filter(Number.isFinite));
  const yDens = useMemo(
    () => scaleLinear({ domain: [0, densMax], range: [h, h * (1 - DENSITY_SHARE)] }),
    [densMax, h],
  );
  const densityPoints = useMemo(
    () => grid.map((x, i) => ({ x, y: density[i] ?? 0 })),
    [grid, density],
  );

  const ordered = useMemo(
    // The selected line is drawn last so it sits on top.
    () => [...kinds].sort((a, b) => Number(a.kind === selected) - Number(b.kind === selected)),
    [kinds, selected],
  );
  const offScale = useMemo(
    () =>
      kinds.flatMap((kind) => {
        const index = kind.curve.findIndex((value) => value > top);
        const price = grid[index];
        return index < 0 || price === undefined ? [] : [{ kind: kind.kind, price }];
      }),
    [kinds, grid, top],
  );
  const selectedKind = kinds.find((kind) => kind.kind === selected) ?? null;
  const bands = viewBands(view, [lo, hi]);
  const closeX = xScale(close);
  const zeroY = yScale(0);
  const stripY = h + STRIP_GAP;

  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const point = localPoint(event);
    if (!point) return;
    const xPx = Math.min(w, Math.max(0, point.x - margin.left));
    const index = nearestIndex(grid, xScale.invert(xPx));
    if (index >= 0) setHover({ index, xPx: xScale(grid[index] ?? lo), top: point.y });
  };

  let tooltip: JSX.Element | null = null;
  if (hover) {
    const price = grid[hover.index];
    const rows = kinds
      .map((kind) => ({ kind: kind.kind, value: kind.curve[hover.index] }))
      .filter((row): row is { kind: StructureKind; value: number } =>
        Number.isFinite(row.value ?? Number.NaN),
      )
      .sort((a, b) => b.value - a.value);
    const lines: TooltipLine[] = [
      { value: usd(price), label: 'price at expiry' },
      ...rows.map((row) => ({
        value: multiple(row.value),
        label: KINDS[row.kind].label,
        color: KINDS[row.kind].color,
        dashed: KINDS[row.kind].credit,
      })),
    ];
    tooltip = (
      <ChartTooltip
        left={margin.left + hover.xPx}
        top={hover.top}
        containerWidth={width}
        lines={lines}
        footer="return on max loss at expiry, highest first"
      />
    );
  }

  const lineLegend: LegendItem[] = kinds.map((kind) => ({
    label: `${DIRECTION_GLYPH[kind.direction]} ${KINDS[kind.kind].label}`,
    color: KINDS[kind.kind].color,
    mark: KINDS[kind.kind].credit ? 'dash' : 'line',
    muted: selected !== null && kind.kind !== selected,
  }));
  const stripKinds = [...new Set(dominance.map((segment) => segment.kind))];
  const stripLegend: LegendItem[] = stripKinds.map((kind) => ({
    label: KINDS[kind].label,
    color: KINDS[kind].color,
    mark: 'square',
  }));

  return (
    <div className="structure-chart">
      <ChartFrame
        width={width}
        height={height}
        margin={margin}
        label="Return on max loss at expiry of the best structure of each kind against the price at expiry, over the calibrated density. The kinds table below holds the same data."
        role="group"
        refreshing={refreshing}
        overlay={tooltip}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={0} y={0} width={w} height={h} />
          </clipPath>
        </defs>

        {bands.map(([from, to]) => (
          <rect
            key={`${from}-${to}`}
            x={xScale(from)}
            y={0}
            width={Math.max(0, xScale(to) - xScale(from))}
            height={h}
            fill="var(--ink-1)"
            fillOpacity={0.07}
            data-testid="view-shade"
          />
        ))}

        <AreaClosed
          data={densityPoints}
          x={(d) => xScale(d.x)}
          y={(d) => yDens(d.y)}
          yScale={yDens}
          curve={curveLinear}
          fill="var(--ink-2)"
          fillOpacity={0.12}
          data-testid="density"
        />

        <GridRows scale={yScale} width={w} numTicks={5} stroke={gridStroke} />
        <AxisLeft
          scale={yScale}
          numTicks={5}
          tickFormat={(v) => multiple(Number(v), 1)}
          hideAxisLine
          hideTicks
          tickLabelProps={leftTickLabel}
        />
        <AxisBottom
          {...axisBase}
          scale={xScale}
          top={h}
          numTicks={Math.max(3, Math.floor(w / 80))}
          tickFormat={(v) => `$${Math.round(Number(v))}`}
          tickLabelProps={bottomTickLabel}
        />
        <text x={-margin.left + 2} y={-6} fill="var(--ink-muted)" fontSize={10}>
          Return on max loss at expiry
        </text>

        <line
          x1={0}
          x2={w}
          y1={zeroY}
          y2={zeroY}
          stroke="var(--ink-2)"
          strokeWidth={1}
          data-testid="zero-line"
        />
        <g data-testid="close-marker">
          <line
            x1={closeX}
            x2={closeX}
            y1={0}
            y2={h}
            stroke="var(--ink-2)"
            strokeWidth={1}
            strokeDasharray="1 3"
            strokeLinecap="round"
          />
          <text x={closeX + 4} y={10} fill="var(--ink-2)" fontSize={11} className="halo">
            {`close ${usd(close)}`}
          </text>
        </g>

        <g clipPath={`url(#${clipId})`}>
          {ordered.map((kind) => {
            const isSelected = kind.kind === selected;
            return (
              <LinePath
                key={kind.kind}
                data={kind.curve.map((y, i) => ({ x: grid[i] ?? lo, y }))}
                defined={(d) => Number.isFinite(d.y)}
                x={(d) => xScale(d.x)}
                y={(d) => yScale(d.y)}
                curve={curveLinear}
                stroke={KINDS[kind.kind].color}
                strokeWidth={isSelected ? 3 : 1.75}
                strokeOpacity={selected === null || isSelected ? 1 : 0.6}
                strokeDasharray={kindDash(kind.kind)}
                strokeLinejoin="round"
                fill="none"
                data-testid={`kind-line-${kind.kind}`}
                data-selected={isSelected ? 'true' : undefined}
              />
            );
          })}
        </g>

        {selectedKind?.breakevens.map((price) =>
          price < lo || price > hi ? null : (
            <line
              key={price}
              x1={xScale(price)}
              x2={xScale(price)}
              y1={zeroY - 6}
              y2={zeroY + 6}
              stroke="var(--ink-1)"
              strokeWidth={2}
              data-testid="breakeven"
            >
              <title>{`breakeven ${usd(price)}`}</title>
            </line>
          ),
        )}

        {offScale.length > 0 && (
          <g data-testid="off-scale">
            {offScale.map(({ kind, price }) => {
              const x = xScale(price);
              return (
                <path
                  key={kind}
                  d={`M${x} -2L${x + 5} 6H${x - 5}Z`}
                  fill={KINDS[kind].color}
                  stroke="var(--surface-1)"
                  strokeWidth={1}
                />
              );
            })}
            <text x={w} y={-6} textAnchor="end" fill="var(--ink-muted)" fontSize={10}>
              {`▲ off scale above ${multiple(top, 1)}`}
            </text>
          </g>
        )}

        <g transform={`translate(0 ${stripY})`} data-testid="dominance-strip">
          <text x={-6} y={STRIP_HEIGHT - 2} textAnchor="end" fill="var(--ink-muted)" fontSize={10}>
            best
          </text>
          {dominance.map((segment, i) => {
            const nextFrom = dominance[i + 1]?.from;
            const from = Math.max(lo, segment.from);
            const to = Math.min(hi, nextFrom ?? segment.to);
            const x0 = xScale(from);
            const x1 = xScale(to);
            return (
              <rect
                key={`${segment.kind}-${segment.from}`}
                x={x0}
                y={0}
                width={Math.max(1, x1 - x0)}
                height={STRIP_HEIGHT}
                fill={KINDS[segment.kind].color}
                stroke="var(--surface-1)"
                strokeWidth={1}
                data-testid="dominance-segment"
                data-kind={segment.kind}
              >
                <title>{`${KINDS[segment.kind].label}: ${usd(segment.from)} to ${usd(segment.to)}`}</title>
              </rect>
            );
          })}
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
          data-testid="payoff-hit"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHover(null)}
        />
      </ChartFrame>
      <div className="scatter__foot">
        <Legend items={lineLegend} />
      </div>
      <div className="scatter__foot" data-testid="dominance-legend">
        <span className="scatter__note">Strip: highest return on max loss at each price</span>
        <Legend items={stripLegend} />
      </div>
    </div>
  );
}
