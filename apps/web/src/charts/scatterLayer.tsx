import { useMemo } from 'react';
import type { PointerEvent } from 'react';
import { localPoint } from '@visx/event';
import { voronoi } from '@visx/voronoi';
import type { SpreadRow } from '../api/types';
import type { LegendItem } from '../components/Legend';
import { SERIES_SHAPES, SERIES_VARS } from '../lib/colors';
import type { SeriesSlot } from '../lib/colors';
import { markerPath } from './axes';
import type { Margin } from './axes';

/** Pieces the spread scatter charts share: marks, selection and hover rings, hit layer, legend. */

export const HOVER_RADIUS = 24;
export const MIN_RADIUS = 4;
export const MAX_RADIUS = 12;

export interface Highlight {
  symbol: string;
  slot: SeriesSlot;
}

export interface PlotPoint {
  row: SpreadRow;
  px: number;
  py: number;
  r: number;
  slot: SeriesSlot | null;
  pinned: 'up' | 'down' | null;
  /** Extra `data-*` attributes for the mark, such as `data-side`. */
  attrs?: Record<string, string>;
}

/** The 95th percentile (1 for an empty list); sizes clamp here so one outlier cannot shrink the rest. */
export function p95(values: number[]): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)))] ?? 1;
}

/** One mark per point; muted points are drawn first so highlighted ones sit on top. */
export function pointMarks(points: readonly PlotPoint[]) {
  const ordered = [...points].sort((a, b) => Number(a.slot !== null) - Number(b.slot !== null));
  return ordered.map((p) => {
    const key = p.row.spread_key;
    const common = {
      'data-underlying': p.row.underlying,
      'data-key': key,
      'data-r': p.r.toFixed(2),
      ...p.attrs,
    };
    if (p.pinned) {
      const flip = p.pinned === 'down' ? `rotate(180 ${p.px} ${p.py})` : undefined;
      return (
        <path
          key={key}
          d={markerPath('triangle', p.px, p.py, 5)}
          transform={flip}
          className={p.slot === null ? 'pt pt--other pt--pinned' : 'pt pt--pinned'}
          data-testid="pt-pinned"
          data-slot={p.slot === null ? 'other' : String(p.slot + 1)}
          fill={p.slot === null ? 'var(--ink-muted)' : SERIES_VARS[p.slot]}
          fillOpacity={p.slot === null ? 0.6 : 1}
          stroke="var(--surface-1)"
          strokeWidth={2}
          {...common}
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
          data-slot="other"
          fill="var(--ink-muted)"
          fillOpacity={0.35}
          {...common}
        />
      );
    }
    return (
      <path
        key={key}
        d={markerPath(SERIES_SHAPES[p.slot] ?? 'circle', p.px, p.py, p.r)}
        className="pt"
        data-testid="pt"
        data-slot={String(p.slot + 1)}
        fill={SERIES_VARS[p.slot]}
        stroke="var(--surface-1)"
        strokeWidth={2}
        {...common}
      />
    );
  });
}

/** A surface ring then an ink ring around the selected point. */
export function SelectionRing({ point }: { point: PlotPoint }) {
  return (
    <g pointerEvents="none" data-testid="selected-ring">
      <circle
        cx={point.px}
        cy={point.py}
        r={point.r + 3}
        fill="none"
        stroke="var(--surface-1)"
        strokeWidth={2}
      />
      <circle
        cx={point.px}
        cy={point.py}
        r={point.r + 5}
        fill="none"
        stroke="var(--ink-1)"
        strokeWidth={2}
      />
    </g>
  );
}

export function HoverRing({ point }: { point: PlotPoint }) {
  return (
    <circle
      cx={point.px}
      cy={point.py}
      r={point.r + 3}
      fill="none"
      stroke="var(--ink-1)"
      strokeWidth={1.5}
      pointerEvents="none"
    />
  );
}

interface ScatterHitProps {
  points: readonly PlotPoint[];
  w: number;
  h: number;
  margin: Margin;
  hovering: boolean;
  onHover: (point: PlotPoint | null) => void;
  onSelect: (row: SpreadRow) => void;
}

/** A transparent rectangle over the plot: the nearest point within the hover radius wins. */
export function ScatterHit({ points, w, h, margin, hovering, onHover, onSelect }: ScatterHitProps) {
  const diagram = useMemo(
    () => voronoi<PlotPoint>({ x: (d) => d.px, y: (d) => d.py, width: w, height: h })([...points]),
    [points, w, h],
  );
  const find = (event: PointerEvent<SVGRectElement>): PlotPoint | null => {
    const point = localPoint(event);
    if (!point) return null;
    const site = diagram.find(point.x - margin.left, point.y - margin.top, HOVER_RADIUS);
    return site ? site.data : null;
  };
  return (
    <rect
      x={0}
      y={0}
      width={w}
      height={h}
      fill="transparent"
      data-testid="scatter-hit"
      style={{ cursor: hovering ? 'pointer' : 'default' }}
      onPointerMove={(event) => onHover(find(event))}
      onPointerLeave={() => onHover(null)}
      onClick={(event) => {
        const point = find(event as unknown as PointerEvent<SVGRectElement>);
        if (point) onSelect(point.row);
      }}
    />
  );
}

/** One legend entry per highlighted underlying (by slot), then the muted rest. */
export function highlightLegend(highlights: readonly Highlight[]): LegendItem[] {
  return [
    ...[...highlights]
      .sort((a, b) => a.slot - b.slot)
      .map((item) => ({
        label: item.symbol,
        color: SERIES_VARS[item.slot],
        mark: SERIES_SHAPES[item.slot] ?? ('circle' as const),
      })),
    { label: 'Other', color: 'var(--ink-muted)', mark: 'circle', muted: true },
  ];
}
