import { describe, expect, it } from 'vitest';
import { frameAtOrBefore, nearestEarlierIndex, strideFrames } from './sessions';

const DATES = [
  '2026-09-28', // Mon
  '2026-09-29',
  '2026-09-30',
  '2026-10-01',
  '2026-10-02', // Fri
  '2026-10-05', // Mon
  '2026-10-06',
  '2026-11-02',
];

describe('nearestEarlierIndex', () => {
  it('finds exact dates and the nearest earlier one', () => {
    expect(nearestEarlierIndex(DATES, '2026-09-30')).toBe(2);
    expect(nearestEarlierIndex(DATES, '2026-10-03')).toBe(4);
    expect(nearestEarlierIndex(DATES, '2027-01-01')).toBe(DATES.length - 1);
  });

  it('falls back to the first session before the range and -1 for an empty list', () => {
    expect(nearestEarlierIndex(DATES, '2020-01-01')).toBe(0);
    expect(nearestEarlierIndex([], '2026-10-02')).toBe(-1);
  });
});

describe('strideFrames', () => {
  it('keeps every session for "every"', () => {
    expect(strideFrames(DATES, 'every')).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });

  it('takes the first session of each week', () => {
    expect(strideFrames(DATES, 'weekly')).toEqual([0, 5, 7]);
  });

  it('takes the first session of each month', () => {
    expect(strideFrames(DATES, 'monthly')).toEqual([0, 3, 7]);
  });

  it('handles an empty list', () => {
    expect(strideFrames([], 'monthly')).toEqual([]);
  });
});

describe('frameAtOrBefore', () => {
  it('maps a session index to the frame at or before it', () => {
    const frames = [0, 3, 7];
    expect(frameAtOrBefore(frames, 0)).toBe(0);
    expect(frameAtOrBefore(frames, 2)).toBe(0);
    expect(frameAtOrBefore(frames, 3)).toBe(1);
    expect(frameAtOrBefore(frames, 6)).toBe(1);
    expect(frameAtOrBefore(frames, 7)).toBe(2);
  });
});
