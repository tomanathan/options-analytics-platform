import { describe, expect, it } from 'vitest';
import { makeDistribution } from '../test/fixtures';
import { crossingX, MONEYNESS_DOMAIN, overlayDomain } from './options';
import type { PlotSeries } from './options';

function seriesOf(): PlotSeries[] {
  return makeDistribution().expirations.flatMap((expiry, i) =>
    expiry.curve ? [{ expiry, curve: expiry.curve, color: `var(--ord-${i + 1})` }] : [],
  );
}

describe('crossingX', () => {
  it('interpolates between the bracketing knots', () => {
    expect(crossingX([90, 100, 110], [0.2, 0.4, 0.9], 0.5)).toBeCloseTo(102, 10);
  });

  it('returns the knot itself when it sits exactly on the level', () => {
    expect(crossingX([1, 2, 3], [0.1, 0.5, 0.9], 0.5)).toBe(2);
  });

  it('is null when the curve never reaches the level', () => {
    expect(crossingX([1, 2], [0.1, 0.3], 0.5)).toBeNull();
    expect(crossingX([], [], 0.5)).toBeNull();
  });
});

describe('overlayDomain', () => {
  it('spans the union of the knots with 2% padding instead of the fixed window', () => {
    const series = seriesOf();
    const all = series.flatMap((s) => s.curve.moneyness);
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const [from, to] = overlayDomain(series, 'moneyness');
    expect(from).toBeCloseTo(lo - 0.02 * (hi - lo), 10);
    expect(to).toBeCloseTo(hi + 0.02 * (hi - lo), 10);
    expect([from, to]).not.toEqual(MONEYNESS_DOMAIN);
  });

  it('uses dollar knots on the strike axis', () => {
    const series = seriesOf();
    const all = series.flatMap((s) => s.curve.knots);
    const [from, to] = overlayDomain(series, 'strike');
    expect(from).toBeLessThan(Math.min(...all));
    expect(to).toBeGreaterThan(Math.max(...all));
  });

  it('falls back to the fixed window without curves', () => {
    expect(overlayDomain([], 'moneyness')).toEqual(MONEYNESS_DOMAIN);
  });
});
