/**
 * Deterministic structures fixtures. Curves come from the legs' payoffs at expiry, the density is
 * a lognormal, and two kinds (bear call spread, long strangle) never qualify so the missing-kind
 * paths are exercised. Returns are per dollar of max loss.
 */
import type {
  DominanceSegment,
  Fill,
  MapChoice,
  OutcomeCell,
  OutcomeMapResponse,
  PresetId,
  StructureKind,
  StructureKindBest,
  StructureQuery,
  StructureRow,
  StructuresResponse,
} from '../api/types';
import { parseLegs } from '../lib/structures';
import { CLOSE, LATEST_SESSION, mapIdFor } from './fixtures';

const round = (value: number, digits = 6) => Number(value.toFixed(digits));

export const STRUCTURE_EXPIRATION = '2026-11-20';
const STRUCTURE_DTE = 49;
const YEARS = round(STRUCTURE_DTE / 365);
const SIGMA = 0.2 * Math.sqrt(YEARS);

/** Moneyness bounds of each preset for the fixture's lognormal (roughly its quantiles). */
const PRESET_BOUNDS: Record<PresetId, { lo: number | null; hi: number | null; outside: boolean }> =
  {
    up: { lo: 1.05, hi: null, outside: false },
    up_moderate: { lo: 1.01, hi: 1.07, outside: false },
    flat: { lo: 0.95, hi: 1.05, outside: false },
    down_moderate: { lo: 0.93, hi: 0.99, outside: false },
    down: { lo: null, hi: 0.95, outside: false },
    big_move: { lo: 0.91, hi: 1.09, outside: true },
  };

function payoff(legs: string, premium: number, s: number): number {
  return (
    parseLegs(legs).reduce((sum, leg) => {
      const intrinsic =
        leg.right === 'C' ? Math.max(s - leg.strike, 0) : Math.max(leg.strike - s, 0);
      return sum + leg.quantity * intrinsic;
    }, 0) - premium
  );
}

function lognormalDensity(s: number): number {
  const z = Math.log(s / CLOSE) / SIGMA + SIGMA / 2;
  return Math.exp(-0.5 * z * z) / (s * SIGMA * Math.sqrt(2 * Math.PI));
}

export const STRUCTURE_GRID = Array.from({ length: 161 }, (_, i) =>
  round(CLOSE * (0.85 + (0.3 * i) / 160), 4),
);

interface Spec {
  kind: StructureKind;
  direction: StructureRow['direction'];
  legs: string;
  premium: number;
  maxLoss: number;
  maxGain: number | null;
  breakevens: number[];
  popGiven: number;
  ifRight: number;
  ifWrong: number;
  tailShare: number;
}

const SPECS: Spec[] = [
  {
    kind: 'long_call',
    direction: 'up',
    legs: '+1 C 520',
    premium: 6.2,
    maxLoss: 6.2,
    maxGain: null,
    breakevens: [526.2],
    popGiven: 0.74,
    ifRight: 1.21,
    ifWrong: -0.93,
    tailShare: 0.31,
  },
  {
    kind: 'long_put',
    direction: 'down',
    legs: '+1 P 505',
    premium: 5.8,
    maxLoss: 5.8,
    maxGain: 499.2,
    breakevens: [499.2],
    popGiven: 0.51,
    ifRight: 0.22,
    ifWrong: -0.71,
    tailShare: 0.08,
  },
  {
    kind: 'bull_call_spread',
    direction: 'up',
    legs: '+1 C 515 / -1 C 530',
    premium: 5.1,
    maxLoss: 5.1,
    maxGain: 9.9,
    breakevens: [520.1],
    popGiven: 0.93,
    ifRight: 1.74,
    ifWrong: -0.62,
    tailShare: 0,
  },
  {
    kind: 'bear_put_spread',
    direction: 'down',
    legs: '+1 P 510 / -1 P 495',
    premium: 5.5,
    maxLoss: 5.5,
    maxGain: 9.5,
    breakevens: [504.5],
    popGiven: 0.55,
    ifRight: 0.18,
    ifWrong: -0.4,
    tailShare: 0,
  },
  {
    kind: 'bull_put_spread',
    direction: 'up',
    legs: '-1 P 510 / +1 P 500',
    premium: -3.6,
    maxLoss: 6.4,
    maxGain: 3.6,
    breakevens: [506.4],
    popGiven: 1,
    ifRight: 0.56,
    ifWrong: -0.35,
    tailShare: 0,
  },
  {
    kind: 'long_straddle',
    direction: 'move',
    legs: '+1 C 510 / +1 P 510',
    premium: 14,
    maxLoss: 14,
    maxGain: null,
    breakevens: [496, 524],
    popGiven: 0.62,
    ifRight: 0.12,
    ifWrong: -0.6,
    tailShare: 0.12,
  },
  {
    kind: 'iron_condor',
    direction: 'range',
    legs: '-1 P 495 / +1 P 490 / -1 C 530 / +1 C 535',
    premium: -1.8,
    maxLoss: 3.2,
    maxGain: 1.8,
    breakevens: [493.2, 531.8],
    popGiven: 0.58,
    ifRight: 0.31,
    ifWrong: -0.8,
    tailShare: 0,
  },
];

function rowOf(spec: Spec, scale = 1): StructureRow {
  return {
    kind: spec.kind,
    direction: spec.direction,
    legs: spec.legs,
    strikes: parseLegs(spec.legs)
      .map((leg) => leg.strike)
      .sort((a, b) => a - b),
    net_premium: round(spec.premium * scale, 4),
    max_loss: round(spec.maxLoss * scale, 4),
    max_gain: spec.maxGain === null ? null : round(spec.maxGain * scale, 4),
    breakevens: spec.breakevens,
    prob_profit: 0.41,
    expected_return: -0.04,
    annualised_return: -0.27,
    reward_to_risk: -0.03,
    prob_profit_given_view: spec.popGiven,
    return_if_right: spec.ifRight,
    return_if_wrong: spec.ifWrong,
    worst_in_view: -0.52,
    pnl_std: 4.1,
    tail_share: spec.tailShare,
  };
}

function curveOf(spec: Spec): number[] {
  return STRUCTURE_GRID.map((s) => round(payoff(spec.legs, spec.premium, s) / spec.maxLoss, 4));
}

/** Contiguous segments of the kind with the highest return at each grid price. */
function dominanceOf(kinds: StructureKindBest[]): DominanceSegment[] {
  const segments: DominanceSegment[] = [];
  STRUCTURE_GRID.forEach((price, i) => {
    let best: StructureKindBest | undefined;
    kinds.forEach((kind) => {
      if (best === undefined || (kind.curve[i] ?? -Infinity) > (best.curve[i] ?? -Infinity))
        best = kind;
    });
    if (!best) return;
    const last = segments[segments.length - 1];
    if (last && last.kind === best.kind) last.to = price;
    else segments.push({ from: price, to: price, kind: best.kind });
  });
  return segments;
}

export function makeStructures(
  query: Partial<StructureQuery> & { symbol?: string; session?: string } = {},
): StructuresResponse {
  const preset = query.preset === undefined ? 'up_moderate' : query.preset;
  const bounds =
    preset === null
      ? { lo: query.lo ?? null, hi: query.hi ?? null, outside: query.outside ?? false }
      : PRESET_BOUNDS[preset];
  const minPop = query.minPopGiven ?? 0.5;
  const fill: Fill = query.fill ?? 'natural';
  // The mid fill is a little cheaper for every structure.
  const scale = fill === 'mid' ? 0.95 : 1;
  const specs = SPECS.filter((spec) => spec.popGiven >= minPop);
  const kinds: StructureKindBest[] = specs.map((spec) => ({
    ...rowOf(spec, scale),
    curve: curveOf(spec),
  }));
  const ranking = specs
    .map((spec) => rowOf(spec, scale))
    .sort((a, b) => (b.return_if_right ?? 0) - (a.return_if_right ?? 0));
  const best = kinds.reduce<StructureKindBest | null>(
    (top, kind) =>
      top === null || (kind.return_if_right ?? -Infinity) > (top.return_if_right ?? -Infinity)
        ? kind
        : top,
    null,
  );
  const spread = kinds.find((k) => k.kind === 'bull_call_spread') ?? null;
  const single = kinds.find((k) => k.kind === 'long_call') ?? null;
  const advantage =
    spread && single
      ? round((spread.return_if_right ?? 0) - (single.return_if_right ?? 0), 4)
      : null;
  return {
    symbol: query.symbol ?? 'SPY',
    session: query.session ?? LATEST_SESSION,
    expiration: query.expiration ?? STRUCTURE_EXPIRATION,
    dte_days: STRUCTURE_DTE,
    years: YEARS,
    underlying_close: CLOSE,
    forward: round(CLOSE * 1.006, 2),
    fill,
    map_id: mapIdFor(query.map ?? 'auto'),
    map_is_identity: false,
    look_ahead: false,
    tails: { sigma_lo: 0.31, sigma_hi: 0.22, mass_lo: 0.012, mass_hi: 0.009, location: 515.4 },
    view: {
      preset,
      lo: bounds.lo === null ? null : round(bounds.lo * CLOSE, 2),
      hi: bounds.hi === null ? null : round(bounds.hi * CLOSE, 2),
      outside: bounds.outside,
      lo_moneyness: bounds.lo,
      hi_moneyness: bounds.hi,
      prob: 0.3,
      prob_market: 0.27,
    },
    grid: STRUCTURE_GRID,
    density: STRUCTURE_GRID.map((s) => round(lognormalDensity(s), 8)),
    kinds,
    ranking,
    dominance: dominanceOf(kinds),
    verdict: {
      best_kind: best?.kind ?? null,
      spread_kind: spread?.kind ?? null,
      single_kind: single?.kind ?? null,
      spread_return_if_right: spread?.return_if_right ?? null,
      single_return_if_right: single?.return_if_right ?? null,
      advantage,
      reason:
        spread && single
          ? 'The view is bounded above at $548.20, so the long call’s payoff beyond it is never collected; the bull call spread returns 1.74x on risk against 1.21x.'
          : 'Too few structures qualify for a comparison of spreads and singles.',
    },
    n_structures: 2140,
    n_qualifying: 1312,
  };
}

const PRESET_LABELS: Record<PresetId, string> = {
  up: 'Up, above the 75th percentile',
  up_moderate: 'Up, moderately (55th to 85th)',
  flat: 'Flat (25th to 75th)',
  down_moderate: 'Down, moderately (15th to 45th)',
  down: 'Down, below the 25th percentile',
  big_move: 'Big move, outside the 10th to 90th',
};

/** Per preset: best kind and the two sides of the comparison, chosen to span the scale. */
const MAP_CELLS: Record<
  PresetId,
  Pick<
    OutcomeCell,
    | 'best_kind'
    | 'best_return_if_right'
    | 'best_legs'
    | 'spread_kind'
    | 'spread_return_if_right'
    | 'single_kind'
    | 'single_return_if_right'
    | 'advantage'
  >
> = {
  up: {
    best_kind: 'long_call',
    best_return_if_right: 2.9,
    best_legs: '+1 C 535',
    spread_kind: 'bull_call_spread',
    spread_return_if_right: 2.1,
    single_kind: 'long_call',
    single_return_if_right: 2.9,
    advantage: -0.8,
  },
  up_moderate: {
    best_kind: 'bull_call_spread',
    best_return_if_right: 1.74,
    best_legs: '+1 C 515 / -1 C 530',
    spread_kind: 'bull_call_spread',
    spread_return_if_right: 1.74,
    single_kind: 'long_call',
    single_return_if_right: 1.21,
    advantage: 0.53,
  },
  flat: {
    best_kind: 'iron_condor',
    best_return_if_right: 0.31,
    best_legs: '-1 P 495 / +1 P 490 / -1 C 530 / +1 C 535',
    spread_kind: 'iron_condor',
    spread_return_if_right: 0.31,
    single_kind: null,
    single_return_if_right: null,
    advantage: null,
  },
  down_moderate: {
    best_kind: 'bear_put_spread',
    best_return_if_right: 1.5,
    best_legs: '+1 P 505 / -1 P 490',
    spread_kind: 'bear_put_spread',
    spread_return_if_right: 1.5,
    single_kind: 'long_put',
    single_return_if_right: 1.45,
    advantage: 0.05,
  },
  down: {
    best_kind: 'long_put',
    best_return_if_right: 2.4,
    best_legs: '+1 P 490',
    spread_kind: 'bear_put_spread',
    spread_return_if_right: 1.9,
    single_kind: 'long_put',
    single_return_if_right: 2.4,
    advantage: -0.5,
  },
  big_move: {
    best_kind: null,
    best_return_if_right: null,
    best_legs: null,
    spread_kind: null,
    spread_return_if_right: null,
    single_kind: null,
    single_return_if_right: null,
    advantage: null,
  },
};

export const MAP_SYMBOLS = ['QQQ', 'SPY', 'XLF'];

export function makeOutcomeMap(
  query: { session?: string; targetDte?: number; fill?: Fill; map?: MapChoice } = {},
): OutcomeMapResponse {
  const session = query.session && query.session !== 'latest' ? query.session : LATEST_SESSION;
  const presets = (Object.keys(PRESET_LABELS) as PresetId[]).map((id) => ({
    id,
    label: PRESET_LABELS[id],
  }));
  return {
    session,
    target_dte: query.targetDte ?? 35,
    fill: query.fill ?? 'natural',
    map_id: mapIdFor(query.map ?? 'auto'),
    presets,
    rows: MAP_SYMBOLS.map((symbol) =>
      symbol === 'QQQ'
        ? {
            symbol,
            expiration: null,
            dte_days: null,
            underlying_close: null,
            cells: [],
            unavailable_reason: 'no expiration with a curve at 7 days or more',
          }
        : {
            symbol,
            expiration: STRUCTURE_EXPIRATION,
            dte_days: STRUCTURE_DTE,
            underlying_close: CLOSE,
            cells: presets.map(({ id }) => {
              const b = PRESET_BOUNDS[id];
              return {
                preset: id,
                lo: b.lo === null ? null : round(b.lo * CLOSE, 2),
                hi: b.hi === null ? null : round(b.hi * CLOSE, 2),
                prob: 0.25,
                prob_market: 0.22,
                ...MAP_CELLS[id],
              };
            }),
            unavailable_reason: null,
          },
    ),
  };
}
