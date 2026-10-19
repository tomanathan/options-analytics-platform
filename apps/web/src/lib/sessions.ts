/** Session-list helpers: binary search and playback strides. Dates are ISO strings (sortable). */

export type Stride = 'every' | 'weekly' | 'monthly';

/**
 * Index of the latest session on or before `date`, or 0 when `date` precedes them all.
 * `sessions` must be ascending. Returns -1 for an empty list.
 */
export function nearestEarlierIndex(sessions: readonly string[], date: string): number {
  if (sessions.length === 0) return -1;
  let lo = 0;
  let hi = sessions.length - 1;
  let found = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((sessions[mid] ?? '') <= date) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

function weekKey(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1));
  // Monday-based week start as the key.
  const offset = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - offset);
  return date.toISOString().slice(0, 10);
}

function periodKey(iso: string, stride: Stride): string {
  if (stride === 'monthly') return iso.slice(0, 7);
  if (stride === 'weekly') return weekKey(iso);
  return iso;
}

/** Indices into `sessions` of the first session of each period (all of them for "every"). */
export function strideFrames(sessions: readonly string[], stride: Stride): number[] {
  const frames: number[] = [];
  let last: string | null = null;
  sessions.forEach((session, index) => {
    const key = periodKey(session, stride);
    if (key !== last) frames.push(index);
    last = key;
  });
  return frames;
}

/** Position within `frames` of the latest frame at or before session index `index`. */
export function frameAtOrBefore(frames: readonly number[], index: number): number {
  let found = 0;
  frames.forEach((frame, position) => {
    if (frame <= index) found = position;
  });
  return found;
}
