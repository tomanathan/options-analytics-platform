import { useMemo, useState } from 'react';
import type { PointerEvent } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { localPoint } from '@visx/event';
import { GridColumns, GridRows } from '@visx/grid';
import { scaleLinear, scaleSqrt } from '@visx/scale';
import { voronoi } from '@visx/voronoi';
import type { SpreadRow } from '../api/types';
import { Legend } from '../components/Legend';
import type { LegendItem } from '../components/Legend';
import { SERIES_SHAPES, SERIES_VARS } from '../lib/colors';
import type { SeriesSlot } from '../lib/colors';
import { pct, percentPointTick, shortDate, strike, usd } from '../lib/format';
import { axisBase, bottomTickLabel, gridStroke, leftTickLabel, markerPath, plotArea } from './axes';
import type { Margin } from './axes';
import { ChartFrame } from './ChartFrame';
import { ChartTooltip } from './ChartTooltip';

/** Rows beyond this return are pinned to the edge so an outlier cannot flatten the plot. */
export const ROC_CLAMP_PCT = 100;
const HOVER_RADIUS = 24;
const MIN_RADIUS = 4;
const MAX_RADIUS = 12;

export interface Highlight {
  symbol: string;
  slot: SeriesSlot;
}

interface PlotPoint {
  row: SpreadRow;
  px: number;
  py: number;
  r: number;
  slot: SeriesSlot | null;
  pinned: 'up' | 'down' | null;
}

interface SpreadScatterProps {
  rows: readonly SpreadRow[];
  highlights: readonly Highlight[];
  selectedKey: string | null;
  onSelect: (row: SpreadRow) => void;
  /** Eligibility threshold as a probability; drawn as a dashed vertical line. */
  minProbProfit: number;
  width: number;
  height: number;
  refreshing?: boolean;
}

function p95(values: number[]): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)))] ?? 1;
}

/** POP against expected ROC. Highlighted underlyings take the three series colours and shapes. */
export function SpreadScatter({
  rows,
  highlights,
  selectedKey,
  onSelect,
  minProbProfit,
  width,
  height,
  refreshing,
}: SpreadScatterProps) {
  const [hover, setHover] = useState<PlotPoint | null>(null);
  const margin: Margin = { top: 14, right: 16, bottom: 40, left: 52 };
  const { w, h } = plotArea(width, height, margin);

  const { xScale, yScale, points, pinnedCount } = useMemo(() => {
    const xs = rows.map((row) => row.prob_profit * 100);
    const ys = rows.map((row) =>
      Math.max(-ROC_CLAMP_PCT, Math.min(ROC_CLAMP_PCT, row.expected_roc * 100)),
    );
    const xLo = Math.min(minProbProfit * 100, ...xs);
    const xHi = Math.max(minProbProfit * 100, ...xs);
    const yLo = Math.min(0, ...ys);
    const yHi = Math.max(0, ...ys);
    const x = scaleLinear({
      domain: [Math.max(0, xLo - 2), Math.min(100, xHi + 2)],
      range: [0, w],
      nice: true,
    });
    const y = scaleLinear({
      domain: [yLo, yHi === yLo ? yHi + 1 : yHi],
      range: [h, 0],
      nice: true,
    });
    const r = scaleSqrt({
      domain: [0, p95(rows.map((row) => row.credit))],
      range: [MIN_RADIUS, MAX_RADIUS],
      clamp: true,
    });
    const slots = new Map(highlights.map((item) => [item.symbol, item.slot]));
    let pinned = 0;
    const plotted: PlotPoint[] = rows.map((row) => {
      const rawY = row.expected_roc * 100;
      const isPinned = rawY > ROC_CLAMP_PCT ? 'up' : rawY < -ROC_CLAMP_PCT ? 'down' : null;
      if (isPinned) pinned += 1;
      return {
        row,
        px: x(row.prob_profit * 100),
        py: y(Math.max(-ROC_CLAMP_PCT, Math.min(ROC_CLAMP_PCT, rawY))),
        r: r(row.credit),
        slot: slots.get(row.underlying) ?? null,
        pinned: isPinned,
      };
    });
    return { xScale: x, yScale: y, points: plotted, pinnedCount: pinned };
  }, [rows, highlights, minProbProfit, w, h]);

  const diagram = useMemo(
    () => voronoi<PlotPoint>({ x: (d) => d.px, y: (d) => d.py, width: w, height: h })(points),
    [points, w, h],
  );

  // Draw muted points first so highlighted ones sit on top.
  const layer = useMemo(() => {
    const ordered = [...points].sort((a, b) => Number(a.slot !== null) - Number(b.slot !== null));
    return ordered.map((p) => {
      const key = p.row.spread_key;
      if (p.pinned) {
        const flip = p.pinned === 'down' ? `rotate(180 ${p.px} ${p.py})` : undefined;
        return (
          <path
            key={key}
            d={markerPath('triangle', p.px, p.py, 5)}
            transform={flip}
            className={p.slot === null ? 'pt pt--other pt--pinned' : 'pt pt--pinned'}
            data-testid="pt-pinned"
            data-underlying={p.row.underlying}
            data-key={p.row.spread_key}
            data-slot={p.slot === null ? 'other' : String(p.slot + 1)}
            fill={p.slot === null ? 'var(--ink-muted)' : SERIES_VARS[p.slot]}
            fillOpacity={p.slot === null ? 0.6 : 1}
            stroke="var(--surface-1)"
            strokeWidth={2}
          />
        );
      }
      if (p.slot === null) {
        return (
          <circle
            key={key}
            cx={p.px}
            cy={p.py}
            r={p.r}
            className="pt pt--other"
            data-testid="pt"
            data-underlying={p.row.underlying}
            data-key={p.row.spread_key}
            data-slot="other"
            fill="var(--ink-muted)"
            fillOpacity={0.35}
          />
        );
      }
      return (
        <path
          key={key}
          d={markerPath(SERIES_SHAPES[p.slot] ?? 'circle', p.px, p.py, p.r)}
          className="pt"
          data-testid="pt"
          data-underlying={p.row.underlying}
          data-key={p.row.spread_key}
          data-slot={String(p.slot + 1)}
          fill={SERIES_VARS[p.slot]}
          stroke="var(--surface-1)"
          strokeWidth={2}
        />
      );
    });
  }, [points]);

  const selected =
    selectedKey === null ? null : (points.find((p) => p.row.spread_key === selectedKey) ?? null);

  const find = (event: PointerEvent<SVGRectElement>): PlotPoint | null => {
    const point = localPoint(event);
    if (!point) return null;
    const site = diagram.find(point.x - margin.left, point.y - margin.top, HOVER_RADIUS);
    return site ? site.data : null;
  };

  const legendItems: LegendItem[] = [
    ...[...highlights]
      .sort((a, b) => a.slot - b.slot)
      .map((item) => ({
        label: item.symbol,
        color: SERIES_VARS[item.slot],
        mark: SERIES_SHAPES[item.slot] ?? ('circle' as const),
      })),
    { label: 'Other', color: 'var(--ink-muted)', mark: 'circle', muted: true },
  ];

  const eligibleX = xScale(minProbProfit * 100);

  return (
    <div className="scatter">
      <ChartFrame
        width={width}
        height={height}
        margin={margin}
        label="Spreads: probability of profit against expected return on risk. Use the table below for the same data."
        role="group"
        refreshing={refreshing}
        overlay={
          hover && (
            <ChartTooltip
              left={margin.left + hover.px}
              top={margin.top + hover.py}
              containerWidth={width}
              lines={[
                {
                  value: `POP ${pct(hover.row.prob_profit)} · ROC ${pct(hover.row.expected_roc)}`,
                },
              ]}
              footer={`${hover.row.underlying} ${strike(hover.row.short_strike)}/${strike(hover.row.long_strike)} · ${shortDate(hover.row.expiration)} · credit ${usd(hover.row.credit)}`}
            />
          )
        }
      >
        <GridRows scale={yScale} width={w} numTicks={5} stroke={gridStroke} />
        <GridColumns scale={xScale} height={h} numTicks={6} stroke={gridStroke} />
        <AxisLeft
          scale={yScale}
          numTicks={5}
          tickFormat={(v) => percentPointTick(Number(v))}
          hideAxisLine
          hideTicks
          tickLabelProps={leftTickLabel}
        />
        <AxisBottom
          {...axisBase}
          scale={xScale}
          top={h}
          numTicks={6}
          tickFormat={(v) => percentPointTick(Number(v))}
          tickLabelProps={bottomTickLabel}
        />
        <text x={w / 2} y={h + 34} textAnchor="middle" fill="var(--ink-muted)" fontSize={11}>
          POP, calibrated
        </text>
        <text x={-margin.left + 2} y={-4} fill="var(--ink-muted)" fontSize={10}>
          E[ROC], holding period
        </text>

        <line x1={0} x2={w} y1={yScale(0)} y2={yScale(0)} stroke="var(--axis)" strokeWidth={1} />
        {eligibleX >= 0 && eligibleX <= w && (
          <g>
            <line
              x1={eligibleX}
              x2={eligibleX}
              y1={0}
              y2={h}
              stroke="var(--ink-2)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <text
              x={eligibleX + 4}
              y={12}
              fill="var(--ink-2)"
              fontSize={11}
            >{`eligibility POP ≥ ${Math.round(minProbProfit * 100)}%`}</text>
          </g>
        )}

        <g>{layer}</g>

        {selected && (
          <g pointerEvents="none" data-testid="selected-ring">
            <circle
              cx={selected.px}
              cy={selected.py}
              r={selected.r + 3}
              fill="none"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
            <circle
              cx={selected.px}
              cy={selected.py}
              r={selected.r + 5}
              fill="none"
              stroke="var(--ink-1)"
              strokeWidth={2}
            />
          </g>
        )}
        {hover && (
          <circle
            cx={hover.px}
            cy={hover.py}
            r={hover.r + 3}
            fill="none"
            stroke="var(--ink-1)"
            strokeWidth={1.5}
            pointerEvents="none"
          />
        )}

        <rect
          x={0}
          y={0}
          width={w}
          height={h}
          fill="transparent"
          data-testid="scatter-hit"
          style={{ cursor: hover ? 'pointer' : 'default' }}
          onPointerMove={(event) => setHover(find(event))}
          onPointerLeave={() => setHover(null)}
          onClick={(event) => {
            const point = find(event as unknown as PointerEvent<SVGRectElement>);
            if (point) onSelect(point.row);
          }}
        />
      </ChartFrame>
      <div className="scatter__foot">
        <Legend items={legendItems} />
        <span className="scatter__note">Size is credit ($/sh).</span>
        {pinnedCount > 0 && (
          <span className="scatter__note" data-testid="pinned-note">
            {pinnedCount} points beyond ±{ROC_CLAMP_PCT}% pinned
          </span>
        )}
      </div>
    </div>
  );
}
