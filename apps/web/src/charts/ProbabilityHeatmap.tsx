import { memo, useState } from 'react';
import { PatternLines } from '@visx/pattern';
import type { HeatmapResponse } from '../api/types';
import { SEQ_STOPS, seqColor } from '../lib/colors';
import { expiryLabel, num, pct, shortDate, strike } from '../lib/format';
import { ChartFrame } from './ChartFrame';
import { ChartTooltip } from './ChartTooltip';
import { plotArea } from './axes';
import type { Margin } from './axes';

const GAP = 2;
const MAX_ROW_HEIGHT = 40;
const LEGEND_BLOCK = 34;
const AXIS_BLOCK = 24;

export type HeatmapVariant = 'raw' | 'calibrated';

/** Total chart height that gives each row a comfortable cell height. */
export function heatmapHeight(rows: number, rowHeight = 34): number {
  return 10 + Math.max(1, rows) * rowHeight + AXIS_BLOCK + LEGEND_BLOCK;
}

interface ProbabilityHeatmapProps {
  data: HeatmapResponse;
  /** Raw or calibrated values; the page passes "calibrated" for the "Both" view. */
  variant: HeatmapVariant;
  width: number;
  height: number;
  refreshing?: boolean;
}

interface Hover {
  row: number;
  col: number;
  left: number;
  top: number;
}

function ProbabilityHeatmapBase({
  data,
  variant,
  width,
  height,
  refreshing,
}: ProbabilityHeatmapProps) {
  const [hover, setHover] = useState<Hover | null>(null);
  const margin: Margin = {
    top: 10,
    right: 12,
    bottom: AXIS_BLOCK + LEGEND_BLOCK,
    left: width < 480 ? 76 : 100,
  };
  const { w, h } = plotArea(width, height, margin);
  const columns = data.moneyness.length;
  const rows = data.rows.length;
  const cw = columns > 0 ? w / columns : 0;
  const ch = rows > 0 ? Math.min(MAX_ROW_HEIGHT, h / rows) : 0;
  const plotH = ch * rows;
  const patternId = 'heatmap-hatch';

  const colOf = (m: number) => data.moneyness.findIndex((value) => Math.abs(value - m) < 1e-9);
  const atmCol = colOf(1);
  const m0 = data.moneyness[0] ?? 0;
  const mLast = data.moneyness[columns - 1] ?? 1;

  const valueAt = (row: number, col: number): number | null => {
    const r = data.rows[row];
    if (!r) return null;
    return (variant === 'raw' ? r.prob_below[col] : r.prob_below_calibrated[col]) ?? null;
  };

  let tooltip: JSX.Element | null = null;
  if (hover) {
    const r = data.rows[hover.row];
    const value = valueAt(hover.row, hover.col);
    const m = data.moneyness[hover.col];
    const k = r?.target_strikes[hover.col];
    if (r) {
      tooltip = (
        <ChartTooltip
          left={hover.left}
          top={hover.top}
          containerWidth={width}
          lines={
            value === null
              ? [{ value: 'no value', label: 'outside quoted strikes, not extrapolated' }]
              : [{ value: pct(value), label: 'P(S<K)' }]
          }
          footer={`K $${strike(k)} · m ${num(m, 2)} · ${shortDate(r.expiration)}`}
        />
      );
    }
  }

  return (
    <ChartFrame
      width={width}
      height={height}
      margin={margin}
      label={`Probability heatmap, ${variant} P(S<K), ${rows} expirations by ${columns} moneyness columns`}
      role="group"
      refreshing={refreshing}
      overlay={tooltip}
    >
      <defs>
        <PatternLines
          id={patternId}
          height={6}
          width={6}
          stroke="var(--ink-muted)"
          strokeWidth={1}
          orientation={['diagonal']}
          background="var(--surface-1)"
        />
        <linearGradient id="heatmap-ramp" x1="0" x2="1" y1="0" y2="0">
          {SEQ_STOPS.map((color, i) => (
            <stop key={color} offset={`${(i / (SEQ_STOPS.length - 1)) * 100}%`} stopColor={color} />
          ))}
        </linearGradient>
      </defs>

      {data.rows.map((row, r) => (
        <g key={row.expiration} transform={`translate(0 ${r * ch})`}>
          <text x={-8} y={ch / 2} textAnchor="end" dy="0.33em" fill="var(--ink-2)" fontSize={11}>
            {expiryLabel(row.expiration, row.dte_days)}
          </text>
          {data.moneyness.map((m, c) => {
            const value = valueAt(r, c);
            const k = row.target_strikes[c];
            const label =
              value === null
                ? `outside quoted strikes, not extrapolated · K $${strike(k)} · m ${num(m, 2)} · ${shortDate(row.expiration)}`
                : `P(S<K) ${pct(value)} · K $${strike(k)} · m ${num(m, 2)} · ${shortDate(row.expiration)}`;
            const active = hover?.row === r && hover.col === c;
            return (
              <rect
                key={c}
                x={c * cw}
                y={0}
                width={Math.max(0, cw - GAP)}
                height={Math.max(0, ch - GAP)}
                fill={value === null ? `url(#${patternId})` : seqColor(value)}
                className={value === null ? 'heatmap-cell hatch' : 'heatmap-cell'}
                stroke={active ? 'var(--ink-1)' : 'none'}
                strokeWidth={1.5}
                role="img"
                aria-label={label}
                onPointerEnter={() =>
                  setHover({
                    row: r,
                    col: c,
                    left: margin.left + c * cw + cw / 2,
                    top: margin.top + r * ch + ch / 2,
                  })
                }
                onPointerLeave={() => setHover(null)}
              />
            );
          })}
          {row.forward_moneyness !== null && mLast > m0 && (
            <g pointerEvents="none">
              {(() => {
                const pos = ((row.forward_moneyness - m0) / (mLast - m0)) * (columns - 1);
                const x = (pos + 0.5) * cw - GAP / 2;
                return (
                  <>
                    <line x1={x} x2={x} y1={0} y2={7} stroke="var(--surface-1)" strokeWidth={4} />
                    <line x1={x} x2={x} y1={0} y2={7} stroke="var(--ink-1)" strokeWidth={2} />
                  </>
                );
              })()}
            </g>
          )}
        </g>
      ))}

      {atmCol >= 0 && (
        <rect
          x={atmCol * cw - 0.5}
          y={-0.5}
          width={Math.max(0, cw - GAP) + 1}
          height={Math.max(0, plotH - GAP) + 1}
          fill="none"
          stroke="var(--ink-1)"
          strokeWidth={1}
          pointerEvents="none"
        />
      )}

      <g transform={`translate(0 ${plotH})`}>
        {data.backtest_grid.map((g) => {
          const c = colOf(g);
          if (c < 0) return null;
          const x = c * cw + (cw - GAP) / 2;
          return (
            <g key={g}>
              <line x1={x} x2={x} y1={2} y2={6} stroke="var(--axis)" />
              <text x={x} y={18} textAnchor="middle" fill="var(--ink-muted)" fontSize={11}>
                {g.toFixed(2)}
              </text>
            </g>
          );
        })}
      </g>

      <g transform={`translate(0 ${plotH + AXIS_BLOCK + 6})`}>
        <rect
          x={0}
          y={0}
          width={Math.min(220, w)}
          height={8}
          rx={2}
          fill="url(#heatmap-ramp)"
          aria-hidden="true"
        />
        <text x={0} y={22} fill="var(--ink-muted)" fontSize={11}>
          0%
        </text>
        <text
          x={Math.min(220, w) / 2}
          y={22}
          fill="var(--ink-muted)"
          fontSize={11}
          textAnchor="middle"
        >
          P(S&lt;K) 50%
        </text>
        <text x={Math.min(220, w)} y={22} fill="var(--ink-muted)" fontSize={11} textAnchor="end">
          100%
        </text>
        <g transform={`translate(${Math.min(220, w) + 24} 0)`}>
          <rect
            width={14}
            height={8}
            fill="url(#heatmap-hatch)"
            stroke="var(--ink-muted)"
            strokeWidth={0.5}
          />
          <text x={20} y={8} fill="var(--ink-muted)" fontSize={11}>
            outside quoted strikes
          </text>
        </g>
      </g>
    </ChartFrame>
  );
}

export const ProbabilityHeatmap = memo(ProbabilityHeatmapBase);
