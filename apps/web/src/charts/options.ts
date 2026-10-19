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

/** Whether the view draws the calibrated curve / the raw curve. */
export const showsCalibrated = (view: View) => view !== 'raw';
export const showsRaw = (view: View) => view !== 'calibrated';
