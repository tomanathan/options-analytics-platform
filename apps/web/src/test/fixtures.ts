/**
 * Deterministic API fixtures, typed from the response models. Distributions come from a lognormal
 * so charts look like real data; spreads include an ineligible extreme-ROC row for the pinned case.
 */
import type {
  CalibrationSummary,
  ChainExpiry,
  ChainQuote,
  ChainResponse,
  DistributionCurve,
  DistributionResponse,
  ExpiryDistribution,
  HeatmapResponse,
  MapChoice,
  SessionsResponse,
  SpreadDetail,
  SpreadRow,
  SpreadsResponse,
  UnderlyingsResponse,
} from '../api/types';

export const SESSION_DATES = [
  '2026-09-24',
  '2026-09-25',
  '2026-09-28',
  '2026-09-29',
  '2026-09-30',
  '2026-10-01',
  '2026-10-02',
];
export const LATEST_SESSION = '2026-10-02';
export const CLOSE = 512.34;

const EXPIRIES = [
  { expiration: '2026-10-09', dte: 7 },
  { expiration: '2026-10-16', dte: 14 },
  { expiration: '2026-10-23', dte: 21 },
  { expiration: '2026-11-20', dte: 49 },
];

const round = (value: number, digits = 6) => Number(value.toFixed(digits));

function erf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-x * x);
  return x >= 0 ? y : -y;
}

const normCdf = (z: number) => 0.5 * (1 + erf(z / Math.SQRT2));

export function makeCurve(close: number, dte: number, calibrated: boolean): DistributionCurve {
  const sigma = 0.18 * Math.sqrt(dte / 365);
  const moneyness = Array.from({ length: 25 }, (_, i) => round(0.76 + i * 0.02, 2));
  const knots = moneyness.map((m) => round(m * close, 2));
  const base = moneyness.map((m) => normCdf((Math.log(m) + (sigma * sigma) / 2) / sigma));
  const cal = base.map((p) => (calibrated ? 0.5 + (p - 0.5) * 0.92 : p));
  const raw = base.map((p, i) => p + 0.004 * Math.sin(i * 1.7));
  const mid = knots.slice(1).map((k, i) => round((k + (knots[i] ?? k)) / 2, 3));
  const diff = (values: number[]) =>
    values
      .slice(1)
      .map((v, i) => round((v - (values[i] ?? v)) / ((knots[i + 1] ?? 1) - (knots[i] ?? 0))));
  return {
    knots,
    moneyness,
    cdf: base.map((p) => round(p)),
    raw_cdf: raw.map((p) => round(p)),
    cdf_calibrated: cal.map((p) => round(p)),
    density_mid: mid,
    density: diff(base),
    density_calibrated: diff(cal),
  };
}

export function mapIdFor(choice: MapChoice): string {
  return choice === 'walk_forward' ? 'fold_2026' : 'production';
}

export function makeDistribution(
  session = LATEST_SESSION,
  choice: MapChoice = 'auto',
  symbol = 'SPY',
): DistributionResponse {
  const mapId = mapIdFor(choice);
  const expirations: ExpiryDistribution[] = EXPIRIES.map((e, i) => ({
    expiration: e.expiration,
    dte_days: e.dte,
    years: round(e.dte / 365),
    forward: round(CLOSE * (1 + 0.04 * (e.dte / 365)), 2),
    underlying_close: CLOSE,
    n_quotes: 52 - i * 4,
    n_knots: 25,
    flags: i === 0 ? ['clipped'] : i === 1 ? ['left_tail_uncovered', 'sparse'] : [],
    short_dated: false,
    curve: makeCurve(CLOSE, e.dte, true),
    unavailable_reason: null,
    settlement_date: i === 0 ? '2026-10-09' : null,
    settlement_close: i === 0 ? 498.2 : null,
    prob_below_settlement: i === 0 ? 0.31 : null,
    prob_below_settlement_calibrated: i === 0 ? 0.33 : null,
  }));
  return {
    symbol,
    session,
    map_choice: choice,
    map_id: mapId,
    map_is_identity: false,
    map_train_max_expiration: '2026-09-18',
    look_ahead: false,
    risk_free_apy: 0.045,
    expirations,
  };
}

export function makeHeatmap(
  session = LATEST_SESSION,
  choice: MapChoice = 'auto',
  symbol = 'SPY',
): HeatmapResponse {
  const moneyness = Array.from({ length: 41 }, (_, i) => round(0.8 + 0.01 * i, 2));
  return {
    symbol,
    session,
    map_id: mapIdFor(choice),
    moneyness,
    backtest_grid: [0.8, 0.9, 1.0, 1.1, 1.2],
    rows: EXPIRIES.map((e, r) => {
      const sigma = 0.18 * Math.sqrt(e.dte / 365);
      // The last row has narrow strike coverage, so its outer cells are null (not extrapolated).
      const lo = r === 3 ? 0.88 : 0.78;
      const hi = r === 3 ? 1.12 : 1.22;
      const p = (m: number) => normCdf((Math.log(m) + (sigma * sigma) / 2) / sigma);
      return {
        expiration: e.expiration,
        dte_days: e.dte,
        target_strikes: moneyness.map((m) => round(m * CLOSE, 2)),
        prob_below: moneyness.map((m) => (m < lo || m > hi ? null : round(p(m)))),
        prob_below_calibrated: moneyness.map((m) =>
          m < lo || m > hi ? null : round(0.5 + (p(m) - 0.5) * 0.92),
        ),
        forward_moneyness: round(1 + 0.04 * (e.dte / 365), 4),
      };
    }),
  };
}

function quotes(expiry: { dte: number }): ChainQuote[] {
  const out: ChainQuote[] = [];
  const base = Math.round(CLOSE / 5) * 5;
  for (let i = -6; i <= 6; i += 1) {
    const strike = base + i * 5;
    const m = round(strike / CLOSE, 4);
    const smile =
      0.16 + 3.2 * Math.pow(m - 1, 2) - 0.35 * (m - 1) + 0.02 * Math.sqrt(7 / expiry.dte);
    (['C', 'P'] as const).forEach((right) => {
      const intrinsic = right === 'C' ? Math.max(CLOSE - strike, 0) : Math.max(strike - CLOSE, 0);
      const mid = round(intrinsic + 6 * Math.exp(-Math.abs(m - 1) * 12), 2);
      const usable = !(right === 'P' && i === -6); // one unusable quote for the muted row
      out.push({
        strike,
        option_right: right,
        bid: usable ? round(mid - 0.05, 2) : 0,
        ask: round(mid + 0.05, 2),
        mid,
        iv: round(smile, 4),
        delta: round(right === 'C' ? 0.5 - (m - 1) * 4 : -0.5 - (m - 1) * 4, 3),
        moneyness: m,
        usable,
      });
    });
  }
  return out;
}

export function makeChain(session = LATEST_SESSION, symbol = 'SPY'): ChainResponse {
  const expirations: ChainExpiry[] = EXPIRIES.map((e) => ({
    expiration: e.expiration,
    dte_days: e.dte,
    quotes: quotes(e),
  }));
  return { symbol, session, underlying_close: CLOSE, expirations };
}

export function makeSessions(symbol = 'SPY'): SessionsResponse {
  return {
    symbol,
    sessions: SESSION_DATES.map((session, i) => ({
      session,
      underlying_close: round(CLOSE + i * 1.7 - 4, 2),
      n_expirations: 4,
      n_quotes: 210,
      atm_iv: round(0.17 + 0.004 * Math.sin(i), 4),
    })),
  };
}

export const UNDERLYINGS: UnderlyingsResponse = {
  latest_session: LATEST_SESSION,
  underlyings: [
    {
      symbol: 'SPY',
      sector: 'Index',
      first_session: '2026-09-24',
      last_session: LATEST_SESSION,
      n_sessions: 7,
    },
    {
      symbol: 'XLF',
      sector: 'Financials',
      first_session: '2026-09-24',
      last_session: LATEST_SESSION,
      n_sessions: 7,
    },
  ],
};

export const CALIBRATION: CalibrationSummary = {
  map_id: 'production',
  n_samples: 487352,
  train_max_expiration: '2026-09-18',
  first_test_year: 2021,
  n_predictions: 410000,
  n_snapshots: 1180,
  n_clusters: 96,
  metrics: [
    {
      metric: 'expected_calibration_error',
      variant: 'raw',
      value: 0.0352,
      ci_low: 0.031,
      ci_high: 0.039,
    },
    {
      metric: 'expected_calibration_error',
      variant: 'calibrated',
      value: 0.0167,
      ci_low: 0.014,
      ci_high: 0.021,
    },
    { metric: 'brier_score', variant: 'raw', value: 0.1267, ci_low: 0.12, ci_high: 0.133 },
    { metric: 'brier_score', variant: 'calibrated', value: 0.1293, ci_low: 0.122, ci_high: 0.136 },
  ],
};

function spread(
  rank: number | null,
  underlying: string,
  short: number,
  width: number,
  overrides: Partial<SpreadRow> = {},
): SpreadRow {
  const credit = round(0.4 + width * 0.12 + (rank ?? 9) * 0.02, 2);
  return {
    spread_key: `${underlying}|2026-10-16|${short}|${short - width}`,
    underlying,
    expiration: '2026-10-16',
    dte_days: 14,
    short_strike: short,
    long_strike: short - width,
    width,
    credit,
    credit_natural: round(credit - 0.1, 2),
    max_loss: round(width - credit, 2),
    breakeven: round(short - credit, 2),
    short_moneyness: 0.93,
    prob_profit: round(0.7 - (rank ?? 9) * 0.01, 3),
    prob_profit_raw: round(0.65 - (rank ?? 9) * 0.01, 3),
    prob_max_loss: 0.2,
    expected_roc: round(0.14 - (rank ?? 9) * 0.005, 4),
    expected_roc_raw: 0.1,
    annualised_roc: round(3.5 - (rank ?? 9) * 0.1, 3),
    kelly_fraction: 0.08,
    eligible: rank !== null,
    rank,
    extrapolated: false,
    flags: [],
    ...overrides,
  };
}

export const SPREAD_ROWS: SpreadRow[] = [
  spread(1, 'TSLA', 370, 2.5, { prob_profit: 0.581, prob_profit_raw: 0.511, expected_roc: 0.1438 }),
  spread(2, 'MSFT', 510, 5),
  spread(3, 'TSLA', 365, 5, { flags: ['sparse'] }),
  spread(4, 'SPY', 505, 5),
  spread(5, 'XLF', 52, 1),
  spread(6, 'MSFT', 505, 5),
  spread(7, 'SPY', 500, 5),
  spread(null, 'XLF', 51, 1, { expected_roc: 2.5, annualised_roc: null, prob_profit: 0.31 }),
  spread(null, 'TSLA', 400, 2.5, { expected_roc: -1.8, prob_profit: 0.22 }),
];

export interface SpreadFilterParams {
  underlyings: string[];
  expiration: string | null;
  minWidth: number | null;
  maxWidth: number | null;
  minPop: number;
  minCredit: number;
  eligibleOnly: boolean;
}

export function makeSpreads(filters: SpreadFilterParams): SpreadsResponse {
  const rows = SPREAD_ROWS.filter(
    (r) =>
      (!filters.eligibleOnly || r.eligible) &&
      (filters.underlyings.length === 0 || filters.underlyings.includes(r.underlying)) &&
      (filters.expiration === null || r.expiration === filters.expiration) &&
      (filters.minWidth === null || r.width >= filters.minWidth) &&
      (filters.maxWidth === null || r.width <= filters.maxWidth) &&
      r.prob_profit >= filters.minPop &&
      r.credit >= filters.minCredit,
  );
  return {
    as_of: LATEST_SESSION,
    source: 'gold',
    total: SPREAD_ROWS.length,
    matched: rows.length,
    min_prob_profit: 0.5,
    underlyings: ['MSFT', 'SPY', 'TSLA', 'XLF'],
    expirations: ['2026-10-16'],
    rows,
  };
}

export function makeSpreadDetail(key: string): SpreadDetail | null {
  const row = SPREAD_ROWS.find((r) => r.spread_key === key);
  if (!row) return null;
  const close = 372.4;
  const lo = row.long_strike - 2 * row.width;
  const hi = close * 1.04 + row.width;
  const prices = Array.from({ length: 41 }, (_, i) => round(lo + ((hi - lo) * i) / 40, 2));
  [row.long_strike, row.short_strike, row.breakeven].forEach((p) => prices.push(p));
  const sorted = [...new Set(prices)].sort((a, b) => a - b);
  const payoff = sorted.map((price) => ({
    price,
    payoff: round(
      row.credit - Math.max(row.short_strike - price, 0) + Math.max(row.long_strike - price, 0),
      4,
    ),
  }));
  const mids = Array.from({ length: 30 }, (_, i) => round(lo + ((hi - lo) * (i + 0.5)) / 30, 2));
  const density = mids.map((m) => round(Math.exp(-Math.pow((m - close) / 14, 2)) / 25, 6));
  return {
    ...row,
    trade_date: LATEST_SESSION,
    years: 0.0384,
    underlying_close: close,
    expected_payoff: 0.27,
    interest: 0.0017,
    annualised_roc_raw: 2.9,
    calibrated: true,
    map_id: 'production',
    cash_apy: 0.04,
    risk_free_apy: 0.045,
    forward: round(close * 1.002, 2),
    payoff,
    density_mid: mids,
    density_raw: density,
    density_calibrated: density.map((d) => round(d * 0.95, 6)),
    regions: {
      prob_max_loss: { raw: 0.2, calibrated: 0.2 },
      prob_partial_loss: { raw: 0.21, calibrated: 0.219 },
      prob_profit: { raw: 0.511, calibrated: 0.581 },
    },
    knot_range: [lo, hi],
  };
}
