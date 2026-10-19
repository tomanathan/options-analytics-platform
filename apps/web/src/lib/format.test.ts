import { describe, expect, it } from 'vitest';
import {
  annualisedRoc,
  axisNumber,
  DASH,
  expiryLabel,
  longDate,
  num,
  pct,
  pctTick,
  ratio,
  shortDate,
  signedPct,
  signedPoints,
  strike,
  usd,
} from './format';

describe('format', () => {
  it('formats percentages and shows a dash for missing values', () => {
    expect(pct(0.234)).toBe('23.4%');
    expect(pct(0.5, 0)).toBe('50%');
    expect(pct(null)).toBe(DASH);
    expect(pct(Number.NaN)).toBe(DASH);
    expect(pct(Number.POSITIVE_INFINITY)).toBe(DASH);
  });

  it('signs returns', () => {
    expect(signedPct(0.1438, 2)).toBe('+14.38%');
    expect(signedPct(-0.05)).toBe('-5.0%');
    expect(signedPct(0)).toBe('0.0%');
    expect(signedPct(null)).toBe(DASH);
  });

  it('formats dollars, negatives with the sign first', () => {
    expect(usd(1.9)).toBe('$1.90');
    expect(usd(-1.5)).toBe('-$1.50');
    expect(usd(512.7, 1)).toBe('$512.7');
    expect(usd(undefined)).toBe(DASH);
  });

  it('trims strikes', () => {
    expect(strike(585)).toBe('585');
    expect(strike(512.5)).toBe('512.5');
    expect(strike(367.25)).toBe('367.25');
    expect(strike(null)).toBe(DASH);
  });

  it('formats fixed decimals', () => {
    expect(num(0.4567, 2)).toBe('0.46');
    expect(num(null)).toBe(DASH);
  });

  it('formats a ratio to two decimals and a dash for missing', () => {
    expect(ratio(0.1472)).toBe('0.15');
    expect(ratio(-0.0279)).toBe('-0.03');
    expect(ratio(2, 1)).toBe('2.0');
    expect(ratio(null)).toBe(DASH);
    expect(ratio(Number.NaN)).toBe(DASH);
  });

  it('signs differences of probabilities in percentage points', () => {
    expect(signedPoints(0.087)).toBe('+8.7');
    expect(signedPoints(-0.131)).toBe('-13.1');
    expect(signedPoints(0)).toBe('0.0');
    expect(signedPoints(-0.0004)).toBe('0.0');
    expect(signedPoints(null)).toBe(DASH);
  });

  it('formats dates without a time-zone shift', () => {
    expect(shortDate('2026-10-16')).toBe('Oct 16');
    expect(shortDate('2026-01-01')).toBe('Jan 1');
    expect(longDate('2026-10-02')).toBe('Oct 2, 2026');
    expect(shortDate('not a date')).toBe('not a date');
    expect(expiryLabel('2026-10-16', 14)).toBe('Oct 16 · 14d');
  });

  it('formats axis ticks', () => {
    expect(pctTick(0.5)).toBe('50%');
    expect(pctTick(0.125)).toBe('12.5%');
    expect(axisNumber(0)).toBe('0');
    expect(axisNumber(12.4)).toBe('12');
    expect(axisNumber(4.25)).toBe('4.3');
    expect(axisNumber(0.00421)).toBe('0.0042');
  });

  it('never prints an unbounded annualised return', () => {
    expect(annualisedRoc(3.4)).toBe('340%');
    expect(annualisedRoc(null)).toBe(DASH);
    expect(annualisedRoc(4.5e13)).toBe('>10,000%');
  });
});
