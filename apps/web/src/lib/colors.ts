import { interpolateLab } from 'd3-interpolate';

/**
 * Colour helpers. CSS references use `var(--token)` so tokens.css stays the single source.
 * The heatmap interpolates in Lab, which needs literal values; `SEQ_STOPS` mirrors
 * `--seq-0..7` and is checked against tokens.css by a test.
 */

export const SEQ_STOPS = [
  '#0d366b',
  '#104281',
  '#184f95',
  '#256abf',
  '#3987e5',
  '#6da7ec',
  '#9ec5f4',
  '#cde2fb',
] as const;

const SEQ_STEPS = 101;
const seqCache: string[] = [];

/** Sequential colour for a probability in [0, 1]; values outside are clamped. */
export function seqColor(p: number): string {
  const clamped = Math.min(1, Math.max(0, p));
  const step = Math.round(clamped * (SEQ_STEPS - 1));
  const cached = seqCache[step];
  if (cached) return cached;
  const position = (step / (SEQ_STEPS - 1)) * (SEQ_STOPS.length - 1);
  const i = Math.min(SEQ_STOPS.length - 2, Math.floor(position));
  const color = interpolateLab(SEQ_STOPS[i] ?? '', SEQ_STOPS[i + 1] ?? '')(position - i);
  seqCache[step] = color;
  return color;
}

/** Ordinal expiry colour (nearest expiry = `--ord-1`), clamped to the four defined steps. */
export function ordColor(index: number): string {
  return `var(--ord-${Math.min(Math.max(index, 0), 3) + 1})`;
}

export const SERIES_VARS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)'] as const;
export type SeriesSlot = 0 | 1 | 2;
export type MarkerShape = 'circle' | 'square' | 'triangle';
export const SERIES_SHAPES: readonly MarkerShape[] = ['circle', 'square', 'triangle'];

/**
 * Keep an underlying's series slot while it stays highlighted; a newly added one takes the
 * lowest free slot. Returns a new record containing only the current highlights.
 */
export function assignSlots(
  previous: Readonly<Record<string, SeriesSlot>>,
  highlights: readonly string[],
): Record<string, SeriesSlot> {
  const next: Record<string, SeriesSlot> = {};
  const used = new Set<number>();
  highlights.forEach((symbol) => {
    const slot = previous[symbol];
    if (slot !== undefined) {
      next[symbol] = slot;
      used.add(slot);
    }
  });
  highlights.forEach((symbol) => {
    if (next[symbol] !== undefined) return;
    const free = ([0, 1, 2] as const).find((slot) => !used.has(slot));
    if (free === undefined) return;
    next[symbol] = free;
    used.add(free);
  });
  return next;
}
