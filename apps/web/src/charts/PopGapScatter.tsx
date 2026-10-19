import { useMemo, useState } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { GridColumns, GridRows } from '@visx/grid';
import { scaleLinear, scaleSqrt } from '@visx/scale';
import type { SpreadRow } from '../api/types';
import { Legend } from '../components/Legend';
import { pct, percentPointTick, shortDate, signedPoints, strike } from '../lib/format';
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

/** Guides above the parity line, in percentage points of POP. */
export const GAP_GUIDES = [5, 10] as const;

const MARGIN: Margin = { top: 14, right: 16, bottom: 40, left: 52 };
const TICKS = [0, 20, 40, 60, 80, 100];

interface PopGapScatterProps {
  rows: readonly SpreadRow[];
  highlights: readonly Highlight[];
  selectedKey: string | null;
  onSelect: (row: SpreadRow) => void;
  width: number;
  height: number;
  refreshing?: boolean;
}

/**
 * Calibrated POP against the POP the credit implies (max loss over width), both 0 to 100%.
 * A point above the parity line has a calibrated probability above the price-implied one;
 * the dashed guides sit 5 and 10 points above it. Point area follows the spread width.
 */
export function PopGapScatter({
  rows,
  highlights,
  selectedKey,
  onSelect,
  width,
  height,
  refreshing,
}: PopGapScatterProps) {
  const [hover, setHover] = useState<PlotPoint | null>(null);
  const { w, h } = plotArea(width, height, MARGIN);

  const { xScale, yScale, points } = useMemo(() => {
    const x = scaleLinear({ domain: [0, 100], range: [0, w] });
    const y = scaleLinear({ domain: [0, 100], range: [h, 0] });
    const r = scaleSqrt({
      domain: [0, p95(rows.map((row) => row.width))],
      range: [MIN_RADIUS, MAX_RADIUS],
      clamp: true,
    });
    const slots = new Map(highlights.map((item) => [item.symbol, item.slot]));
    const plotted: PlotPoint[] = rows.map((row) => ({
      row,
      px: x(row.pop_implied * 100),
      py: y(row.prob_profit * 100),
      r: r(row.width),
      slot: slots.get(row.underlying) ?? null,
      pinned: null,
      attrs: { 'data-side': row.prob_profit > row.pop_implied ? 'above' : 'below' },
    }));
    return { xScale: x, yScale: y, points: plotted };
  }, [rows, highlights, w, h]);

  const layer = useMemo(() => pointMarks(points), [points]);
  const selected =
    selectedKey === null ? null : (points.find((p) => p.row.spread_key === selectedKey) ?? null);

  const legendItems = [
    ...highlightLegend(highlights),
    { label: 'Calibrated = implied', color: 'var(--ink-1)', mark: 'line' as const },
    { label: '+5 / +10 points', color: 'var(--ink-muted)', mark: 'dash' as const },
  ];

  return (
    <div className="scatter">
      <ChartFrame
        width={width}
        height={height}
        margin={MARGIN}
        label="Spreads: calibrated probability of profit against the probability the credit implies. Use the table below for the same data."
        role="group"
        refreshing={refreshing}
        overlay={
          hover && (
            <ChartTooltip
              left={MARGIN.left + hover.px}
              top={MARGIN.top + hover.py}
              containerWidth={width}
              lines={[
                {
                  value: `POP cal ${pct(hover.row.prob_profit)} · price-implied ${pct(hover.row.pop_implied)} · gap ${signedPoints(hover.row.pop_gap)} pts · raw gap ${signedPoints(hover.row.prob_profit_raw - hover.row.pop_implied)} pts`,
                },
              ]}
              footer={`${hover.row.underlying} ${strike(hover.row.short_strike)}/${strike(hover.row.long_strike)} · ${shortDate(hover.row.expiration)}`}
            />
          )
        }
      >
        <GridRows scale={yScale} width={w} tickValues={TICKS} stroke={gridStroke} />
        <GridColumns scale={xScale} height={h} tickValues={TICKS} stroke={gridStroke} />
        <AxisLeft
          scale={yScale}
          tickValues={TICKS}
          tickFormat={(v) => percentPointTick(Number(v))}
          hideAxisLine
          hideTicks
          tickLabelProps={leftTickLabel}
        />
        <AxisBottom
          {...axisBase}
          scale={xScale}
          top={h}
          tickValues={TICKS}
          tickFormat={(v) => percentPointTick(Number(v))}
          tickLabelProps={bottomTickLabel}
        />
        <text x={w / 2} y={h + 34} textAnchor="middle" fill="var(--ink-muted)" fontSize={11}>
          Price-implied POP (max loss ÷ width)
        </text>
        <text x={-MARGIN.left + 2} y={-4} fill="var(--ink-muted)" fontSize={10}>
          POP, calibrated
        </text>

        {GAP_GUIDES.map((gap) => (
          <g key={gap} data-testid="gap-guide" data-gap={String(gap)}>
            <line
              x1={xScale(0)}
              y1={yScale(gap)}
              x2={xScale(100 - gap)}
              y2={yScale(100)}
              stroke="var(--ink-muted)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <text x={xScale(0) + 4} y={yScale(gap) - 4} fill="var(--ink-muted)" fontSize={10}>
              {`+${gap} pts`}
            </text>
          </g>
        ))}
        <line
          x1={xScale(0)}
          y1={yScale(0)}
          x2={xScale(100)}
          y2={yScale(100)}
          stroke="var(--ink-1)"
          strokeWidth={1.5}
          data-testid="parity-line"
        />

        <g>{layer}</g>

        {selected && <SelectionRing point={selected} />}
        {hover && <HoverRing point={hover} />}

        <ScatterHit
          points={points}
          w={w}
          h={h}
          margin={MARGIN}
          hovering={hover !== null}
          onHover={setHover}
          onSelect={onSelect}
        />
      </ChartFrame>
      <div className="scatter__foot">
        <Legend items={legendItems} />
        <span className="scatter__note">Size is spread width ($).</span>
      </div>
      <p className="scatter__note scatter__region">
        Above the line: the calibrated probability of profit exceeds the probability the credit
        implies (ROI = odds; price-implied POP = max loss ÷ width).
      </p>
    </div>
  );
}
