/** Display formatting. Probabilities and ratios arrive as decimals; money is $ per share. */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const DASH = '–';

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** 0.234 -> "23.4%". Null or non-finite -> en dash. */
export function pct(value: number | null | undefined, digits = 1): string {
  return finite(value) ? `${(value * 100).toFixed(digits)}%` : DASH;
}

/** 0.129 -> "+12.9%". */
export function signedPct(value: number | null | undefined, digits = 1): string {
  if (!finite(value)) return DASH;
  const text = (value * 100).toFixed(digits);
  return value > 0 ? `+${text}%` : `${text}%`;
}

/** 1.9 -> "$1.90". */
export function usd(value: number | null | undefined, digits = 2): string {
  if (!finite(value)) return DASH;
  return value < 0 ? `-$${Math.abs(value).toFixed(digits)}` : `$${value.toFixed(digits)}`;
}

/** A strike without trailing zeros: 585 -> "585", 512.5 -> "512.5", 370 -> "370". */
export function strike(value: number | null | undefined): string {
  if (!finite(value)) return DASH;
  return String(Number(value.toFixed(3)));
}

/** Fixed decimals, en dash for missing. */
export function num(value: number | null | undefined, digits = 2): string {
  return finite(value) ? value.toFixed(digits) : DASH;
}

/** A dimensionless ratio such as reward/risk: 0.1472 -> "0.15". Null or non-finite -> en dash. */
export function ratio(value: number | null | undefined, digits = 2): string {
  return finite(value) ? value.toFixed(digits) : DASH;
}

/** A difference of probabilities in percentage points: 0.087 -> "+8.7", -0.004 -> "-0.4". */
export function signedPoints(value: number | null | undefined, digits = 1): string {
  if (!finite(value)) return DASH;
  const text = (value * 100).toFixed(digits);
  // A value that rounds to zero carries no sign.
  return Number(text) > 0 ? `+${text}` : Number(text) === 0 ? (0).toFixed(digits) : text;
}

/** Density in 1/$ with a sensible precision. */
export function density(value: number): string {
  if (!Number.isFinite(value)) return DASH;
  if (value === 0) return '0';
  return value >= 0.01 ? value.toFixed(4) : value.toExponential(2);
}

function parts(iso: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

/** "2026-10-16" -> "Oct 16". Pure string work, so no time zone can shift the day. */
export function shortDate(iso: string): string {
  const p = parts(iso);
  if (!p) return iso;
  return `${MONTHS[p.month - 1] ?? ''} ${p.day}`;
}

/** "2026-10-16" -> "Oct 16, 2026". */
export function longDate(iso: string): string {
  const p = parts(iso);
  return p ? `${shortDate(iso)}, ${p.year}` : iso;
}

/** "Oct 16 · 14d". */
export function expiryLabel(expiration: string, dteDays: number): string {
  return `${shortDate(expiration)} · ${dteDays}d`;
}

/** Axis tick for a 0..1 probability: 0.5 -> "50%". */
export function pctTick(value: number): string {
  return `${Math.round(value * 1000) / 10}%`;
}

/** Whole-number percentage tick for values already in percent. */
export function percentPointTick(value: number): string {
  return `${Math.round(value * 10) / 10}%`;
}

/** Annualised return on max loss can be huge or missing; cap the display rather than print 13 digits. */
export function annualisedRoc(value: number | null | undefined): string {
  if (!finite(value)) return DASH;
  if (Math.abs(value) >= 100) return '>10,000%';
  return pct(value, 0);
}

/** Compact tick for small positive quantities such as densities: 0, 0.0042, 0.35, 4.2, 12. */
export function axisNumber(value: number): string {
  if (!Number.isFinite(value) || value === 0) return '0';
  const abs = Math.abs(value);
  if (abs >= 10) return String(Math.round(value));
  if (abs >= 1) return String(Number(value.toFixed(1)));
  return String(Number(value.toPrecision(2)));
}

/** A return per dollar of max loss as a multiple: 1.74 -> "1.74×", -0.5 -> "-0.50×". */
export function multiple(value: number | null | undefined, digits = 2): string {
  return finite(value) ? `${value.toFixed(digits)}×` : DASH;
}

/** A signed multiple, for differences of returns: 0.53 -> "+0.53×", -0.8 -> "-0.80×". */
export function signedMultiple(value: number | null | undefined, digits = 2): string {
  if (!finite(value)) return DASH;
  const text = value.toFixed(digits);
  if (Number(text) > 0) return `+${text}×`;
  return Number(text) === 0 ? `${(0).toFixed(digits)}×` : `${text}×`;
}
