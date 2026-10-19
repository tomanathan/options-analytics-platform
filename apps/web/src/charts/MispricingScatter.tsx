import { useMemo, useState } from 'react';
import { AxisBottom, AxisLeft } from '@visx/axis';
import { GridColumns, GridRows } from '@visx/grid';
import { scaleLog, scaleSqrt } from '@visx/scale';
import type { SpreadRow } from '../api/types';
import { Legend } from '../components/Legend';
import { pct, shortDate, strike, usd } from '../lib/format';
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

/** Credits below this ($/sh) are pinned to the axis floor: a log axis has no zero. */
export const CREDIT_FLOOR = 0.01;

/** Edge guides, as a share of the mid credit: the fair credit is (1 - edge) times the mid. */
export const EDGE_GUIDES = [0.25, 0.5, 0.75] as const;

const MARGIN: Margin = { top: 14, right: 16, bottom: 40, left: 56 };

interface MispricingScatterProps {
  rows: readonly SpreadRow[];
  highlights: readonly Highlight[];
  selectedKey: string | null;
  onSelect: (row: SpreadRow) => void;
  width: number;
  height: number;
  refreshing?: boolean;
}

/** 1-2-5 ticks inside `[lo, hi]`, for a log axis. */
export function logTicks(lo: number, hi: number): number[] {
  const ticks: number[] = [];
  const first = Math.floor(Math.log10(lo));
  const last = Math.ceil(Math.log10(hi));
  for (let decade = first; decade <= last; decade += 1) {
    for (const mantissa of [1, 2, 5]) {
      const value = Number((mantissa * 10 ** decade).toPrecision(6));
      if (value >= lo * (1 - 1e-9) && value <= hi * (1 + 1e-9)) ticks.push(value);
    }
  }
  return ticks;
}

function creditTick(value: number): string {
  return value >= 1 ? `$${Number(value.toPrecision(3))}` : `$${value.toFixed(2)}`;
}

/**
 * Market (mid) credit against calibrated fair credit on log-log axes, so every point above the
 * parity line has a mid credit higher than the calibrated fair credit. The dashed guides mark an
 * edge of 25, 50 and 75% of the mid credit. Point area follows the spread width.
 */
export function MispricingScatter({
  rows,
  highlights,
  selectedKey,
  onSelect,
  width,
  height,
  refreshing,
}: MispricingScatterProps) {
  const [hover, setHover] = useState<PlotPoint | null>(null);
  const { w, h } = plotArea(width, height, MARGIN);

  const { xScale, yScale, points, pinnedCount, lo, hi } = useMemo(() => {
    const values = rows.flatMap((row) => [
      Math.max(CREDIT_FLOOR, row.fair_credit),
      Math.max(CREDIT_FLOOR, row.credit),
    ]);
    const low = values.length === 0 ? CREDIT_FLOOR : Math.min(...values);
    const high = values.length === 0 ? 1 : Math.max(...values);
    // One domain on both axes keeps the parity line at 45 degrees.
    const domain: [number, number] = low === high ? [low / 2, high * 2] : [low, high];
    const x = scaleLog({ domain, range: [0, w], nice: true });
    const y = scaleLog({ domain, range: [h, 0], nice: true });
    const [niceLo = low, niceHi = high] = x.domain();
    const r = scaleSqrt({
      domain: [0, p95(rows.map((row) => row.width))],
      range: [MIN_RADIUS, MAX_RADIUS],
      clamp: true,
    });
    const slots = new Map(highlights.map((item) => [item.symbol, item.slot]));
    let pinned = 0;
    const plotted: PlotPoint[] = rows.map((row) => {
      const isPinned = row.fair_credit < CREDIT_FLOOR || row.credit < CREDIT_FLOOR;
      if (isPinned) pinned += 1;
      return {
        row,
        px: x(Math.max(CREDIT_FLOOR, row.fair_credit)),
        py: y(Math.max(CREDIT_FLOOR, row.credit)),
        r: r(row.width),
        slot: slots.get(row.underlying) ?? null,
        pinned: isPinned ? 'down' : null,
        attrs: { 'data-side': row.credit > row.fair_credit ? 'above' : 'below' },
      };
    });
    return {
      xScale: x,
      yScale: y,
      points: plotted,
      pinnedCount: pinned,
      lo: niceLo,
      hi: niceHi,
    };
  }, [rows, highlights, w, h]);

  const layer = useMemo(() => pointMarks(points), [points]);
  const ticks = useMemo(() => logTicks(lo, hi), [lo, hi]);
  const selected =
    selectedKey === null ? null : (points.find((p) => p.row.spread_key === selectedKey) ?? null);

  const guides = EDGE_GUIDES.flatMap((edge) => {
    const slope = 1 / (1 - edge);
    // y = slope * x runs from (lo, slope * lo) to (hi / slope, hi) inside the plot.
    if (lo * slope >= hi) return [];
    return [
      {
        edge,
        x1: xScale(lo),
        y1: yScale(lo * slope),
        x2: xScale(hi / slope),
        y2: yScale(hi),
      },
    ];
  });

  const legendItems = [
    ...highlightLegend(highlights),
    { label: 'Market = fair', color: 'var(--ink-1)', mark: 'line' as const },
    { label: 'Edge 25 / 50 / 75%', color: 'var(--ink-muted)', mark: 'dash' as const },
  ];

  return (
    <div className="scatter">
      <ChartFrame
        width={width}
        height={height}
        margin={MARGIN}
        label="Spreads: market mid credit against calibrated fair credit, log scale. Use the table below for the same data."
        role="group"
        refreshing={refreshing}
        overlay={
          hover && (
            <ChartTooltip
              left={MARGIN.left + hover.px}
              top={MARGIN.top + hover.py}
              containerWidth={width}
              lines={[
                { value: usd(hover.row.credit), label: 'mid' },
                { value: usd(hover.row.credit_natural), label: 'natural' },
                { value: usd(hover.row.fair_credit), label: 'fair, calibrated' },
                {
                  value: `${usd(hover.row.edge)} · ${pct(hover.row.edge_pct)}`,
                  label: 'edge',
                },
              ]}
              footer={`${hover.row.underlying} ${strike(hover.row.short_strike)}/${strike(hover.row.long_strike)} · ${shortDate(hover.row.expiration)}`}
            />
          )
        }
      >
        <GridRows scale={yScale} width={w} tickValues={ticks} stroke={gridStroke} />
        <GridColumns scale={xScale} height={h} tickValues={ticks} stroke={gridStroke} />
        <AxisLeft
          scale={yScale}
          tickValues={ticks}
          tickFormat={(v) => creditTick(Number(v))}
          hideAxisLine
          hideTicks
          tickLabelProps={leftTickLabel}
        />
        <AxisBottom
          {...axisBase}
          scale={xScale}
          top={h}
          tickValues={ticks}
          tickFormat={(v) => creditTick(Number(v))}
          tickLabelProps={bottomTickLabel}
        />
        <text x={w / 2} y={h + 34} textAnchor="middle" fill="var(--ink-muted)" fontSize={11}>
          Calibrated fair credit, $/sh (log scale)
        </text>
        <text x={-MARGIN.left + 2} y={-4} fill="var(--ink-muted)" fontSize={10}>
          Market (mid) credit, $/sh (log scale)
        </text>

        {guides.map((guide) => (
          <g key={guide.edge} data-testid="edge-guide" data-edge={String(guide.edge)}>
            <line
              x1={guide.x1}
              y1={guide.y1}
              x2={guide.x2}
              y2={guide.y2}
              stroke="var(--ink-muted)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <text x={guide.x1 + 4} y={guide.y1 - 4} fill="var(--ink-muted)" fontSize={10}>
              {`edge ${Math.round(guide.edge * 100)}%`}
            </text>
          </g>
        ))}
        <line
          x1={xScale(lo)}
          y1={yScale(lo)}
          x2={xScale(hi)}
          y2={yScale(hi)}
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
        {pinnedCount > 0 && (
          <span className="scatter__note" data-testid="pinned-note">
            {pinnedCount} points below ${CREDIT_FLOOR.toFixed(2)} pinned to the axis floor
          </span>
        )}
      </div>
      <p className="scatter__note scatter__region">
        Above the line: market credit exceeds the calibrated fair credit.
      </p>
    </div>
  );
}
