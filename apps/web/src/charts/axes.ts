import type { MarkerShape } from '../lib/colors';

/** Shared chart geometry and axis styling. Colours are CSS tokens, never literals. */

export interface Margin {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/** Drawable size inside the margins (never negative). */
export function plotArea(width: number, height: number, margin: Margin): { w: number; h: number } {
  return {
    w: Math.max(0, width - margin.left - margin.right),
    h: Math.max(0, height - margin.top - margin.bottom),
  };
}

export const TICK_FONT_SIZE = 11;

/** Props common to every axis: recessive hairlines and muted tabular tick labels. */
export const axisBase = {
  stroke: 'var(--axis)',
  tickStroke: 'var(--axis)',
  tickLength: 4,
} as const;

export const bottomTickLabel = () =>
  ({
    fill: 'var(--ink-muted)',
    fontSize: TICK_FONT_SIZE,
    textAnchor: 'middle',
    dy: '0.25em',
  }) as const;

export const leftTickLabel = () =>
  ({
    fill: 'var(--ink-muted)',
    fontSize: TICK_FONT_SIZE,
    textAnchor: 'end',
    dx: '-0.25em',
    dy: '0.33em',
  }) as const;

export const gridStroke = 'var(--grid)';

/** Index of the entry in an ascending array closest to `target`. Returns -1 for an empty array. */
export function nearestIndex(values: readonly number[], target: number): number {
  if (values.length === 0) return -1;
  let lo = 0;
  let hi = values.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((values[mid] ?? 0) < target) lo = mid + 1;
    else hi = mid;
  }
  const upper = lo;
  const lower = Math.max(0, lo - 1);
  return Math.abs((values[lower] ?? 0) - target) <= Math.abs((values[upper] ?? 0) - target)
    ? lower
    : upper;
}

/** SVG path for a centred marker of radius `r`. */
export function markerPath(shape: MarkerShape, cx: number, cy: number, r: number): string {
  if (shape === 'square') {
    return `M${cx - r} ${cy - r}H${cx + r}V${cy + r}H${cx - r}Z`;
  }
  if (shape === 'triangle') {
    const h = r * 1.15;
    return `M${cx} ${cy - h}L${cx + r * 1.1} ${cy + h * 0.8}H${cx - r * 1.1}Z`;
  }
  return `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
}

/** A value of `NaN` or infinity is never drawn. */
export function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
