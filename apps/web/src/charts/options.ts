import type { DistributionCurve, ExpiryDistribution } from '../api/types';

/** Which probability curve is drawn. "Both" shows calibrated and raw together. */
export type View = 'raw' | 'calibrated' | 'both';
export type XMode = 'moneyness' | 'strike';
export type Layout = 'multiples' | 'overlay';

/** Fixed moneyness window of the landscape charts. */
export const MONEYNESS_DOMAIN: [number, number] = [0.7, 1.3];

/** A drawable curve of one expiry together with the colour it is drawn in. */
export interface PlotSeries {
  expiry: ExpiryDistribution;
  curve: DistributionCurve;
  color: string;
}

/** x values of a curve's knots for the chosen axis. */
export function curveX(curve: DistributionCurve, mode: XMode): number[] {
  return mode === 'moneyness' ? curve.moneyness : curve.knots;
}

/** x position of a dollar level (forward, close, settlement) for the chosen axis. */
export function levelX(price: number, close: number | null, mode: XMode): number | null {
  if (mode === 'strike') return price;
  return close !== null && close > 0 ? price / close : null;
}

/** Shared x domain: fixed moneyness window, or the union of the session's knots in dollars. */
export function xDomainFor(expiries: readonly ExpiryDistribution[], mode: XMode): [number, number] {
  if (mode === 'moneyness') return MONEYNESS_DOMAIN;
  let lo = Infinity;
  let hi = -Infinity;
  for (const expiry of expiries) {
    const knots = expiry.curve?.knots ?? [];
    const first = knots[0];
    const last = knots[knots.length - 1];
    if (first !== undefined) lo = Math.min(lo, first);
    if (last !== undefined) hi = Math.max(hi, last);
  }
  return Number.isFinite(lo) && Number.isFinite(hi) && hi > lo ? [lo, hi] : [0, 1];
}

/** Padding added to each side of the overlay's x domain, as a share of the knot span. */
export const OVERLAY_PADDING = 0.02;

/** x domain of the overlay: the union of the series' knots plus 2% of the span on each side. */
export function overlayDomain(series: readonly PlotSeries[], mode: XMode): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const item of series) {
    for (const x of curveX(item.curve, mode)) {
      if (!Number.isFinite(x)) continue;
      lo = Math.min(lo, x);
      hi = Math.max(hi, x);
    }
  }
  if (!(hi > lo)) return mode === 'moneyness' ? MONEYNESS_DOMAIN : [0, 1];
  const pad = (hi - lo) * OVERLAY_PADDING;
  return [lo - pad, hi + pad];
}

/**
 * x at which a monotone curve first reaches `level`, interpolated linearly between the two
 * bracketing knots. Null when the curve never reaches it. Used for the median (level 0.5).
 */
export function crossingX(
  xs: readonly number[],
  ys: readonly number[],
  level: number,
): number | null {
  for (let i = 0; i < xs.length; i += 1) {
    const y1 = ys[i];
    const x1 = xs[i];
    if (y1 === undefined || x1 === undefined || !Number.isFinite(y1) || y1 < level) continue;
    const y0 = ys[i - 1];
    const x0 = xs[i - 1];
    if (i === 0 || y0 === undefined || x0 === undefined || !Number.isFinite(y0)) return x1;
    return y1 === y0 ? x1 : x0 + ((level - y0) / (y1 - y0)) * (x1 - x0);
  }
  return null;
}

/** Whether the view draws the calibrated curve / the raw curve. */
export const showsCalibrated = (view: View) => view !== 'raw';
export const showsRaw = (view: View) => view !== 'calibrated';
