import { useMemo, useState } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { GridColumns, GridRows } from '@visx/grid';
import { scaleLinear, scaleSqrt } from '@visx/scale';
import type { SpreadRow } from '../api/types';
import { Legend } from '../components/Legend';
import { pct, percentPointTick, shortDate, strike, usd } from '../lib/format';
import { axisBase, bottomTickLabel, gridStroke, leftTickLabel, plotArea } from './axes';
import type { Margin } from './axes';
import { ChartFrame } from './ChartFrame';
import { ChartTooltip } from './ChartTooltip';
import {
  highlightLegend,
  HoverRing,
  MAX_RADIUS,
  MIN_RADIUS,
  p95,
  pointMarks,
  ScatterHit,
  SelectionRing,
} from './scatterLayer';
import type { Highlight, PlotPoint } from './scatterLayer';

export type { Highlight } from './scatterLayer';

/** Rows beyond this return are pinned to the edge so an outlier cannot flatten the plot. */
export const ROC_CLAMP_PCT = 100;

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

/** POP against expected return on max loss. Highlighted underlyings take the three series colours and shapes. */
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

  const layer = useMemo(() => pointMarks(points), [points]);

  const selected =
    selectedKey === null ? null : (points.find((p) => p.row.spread_key === selectedKey) ?? null);

  const legendItems = highlightLegend(highlights);

  const eligibleX = xScale(minProbProfit * 100);

  return (
    <div className="scatter">
      <ChartFrame
        width={width}
        height={height}
        margin={margin}
        label="Spreads: probability of profit against expected return on max loss. Use the table below for the same data."
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
                  value: `POP ${pct(hover.row.prob_profit)} · E[R/max loss] ${pct(hover.row.expected_roc)}`,
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
          Expected return on max loss, holding period
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

        {selected && <SelectionRing point={selected} />}
        {hover && <HoverRing point={hover} />}

        <ScatterHit
          points={points}
          w={w}
          h={h}
          margin={margin}
          hovering={hover !== null}
          onHover={setHover}
          onSelect={onSelect}
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
