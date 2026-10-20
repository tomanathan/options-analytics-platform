/**
 * API types. Components import them only from here. Response types are aliases of the schema
 * generated from `openapi.json` (`npm run gen:api`); do not hand-edit `schema.ts`.
 * Dates are ISO `YYYY-MM-DD` strings; $ are dollars per share; vol and probabilities are decimals.
 */
import type { components } from './schema';

type Schemas = components['schemas'];

export type IsoDate = string;

export type Underlying = Schemas['Underlying'];
export type UnderlyingsResponse = Schemas['UnderlyingsResponse'];
export type SessionSummary = Schemas['SessionSummary'];
export type SessionsResponse = Schemas['SessionsResponse'];
export type ChainQuote = Schemas['ChainQuote'];
export type ChainExpiry = Schemas['ChainExpiry'];
export type ChainResponse = Schemas['ChainResponse'];
export type DistributionCurve = Schemas['DistributionCurve'];
export type ExpiryDistribution = Schemas['ExpiryDistribution'];
export type DistributionResponse = Schemas['DistributionResponse'];
export type HeatmapRow = Schemas['HeatmapRow'];
export type HeatmapResponse = Schemas['HeatmapResponse'];
export type SpreadRow = Schemas['SpreadRow'];
export type SpreadsResponse = Schemas['SpreadsResponse'];
export type SpreadSort = SpreadsResponse['sort'];
export type SpreadDetail = Schemas['SpreadDetail'];
export type PayoffPoint = Schemas['PayoffPoint'];
export type MetricValue = Schemas['MetricValue'];
export type CalibrationSummary = Schemas['CalibrationSummary'];
export type ErrorBody = Schemas['ErrorBody'];
export type HealthResponse = Schemas['HealthResponse'];

export type ErrorCode = ErrorBody['code'];
export type MapChoice = DistributionResponse['map_choice'];

/** Filters sent to `GET /api/spreads`; maps to the endpoint's query parameters. */
export interface SpreadQuery {
  underlying: string[];
  expiration: IsoDate | null;
  minWidth: number | null;
  maxWidth: number | null;
  minPop: number;
  minCredit: number;
  eligibleOnly: boolean;
  /** Smallest edge as a share of the mid credit (0.2 is 20%), or null for no floor. */
  minEdgePct: number | null;
  sort: SpreadSort;
  /** Most rows returned; null leaves the API default. */
  limit: number | null;
}

/*
 * Structures (`/api/structures`). Hand-typed from the JSON shapes in docs/design/structures.md
 * until the generated schema carries them. Returns are per dollar of max loss (1.74 is 1.74x);
 * a NaN on the server (no mass in or outside the view) arrives as null.
 */

export type StructureKind =
  | 'long_call'
  | 'long_put'
  | 'bull_call_spread'
  | 'bear_put_spread'
  | 'bull_put_spread'
  | 'bear_call_spread'
  | 'long_straddle'
  | 'long_strangle'
  | 'iron_condor';
export type StructureDirection = 'up' | 'down' | 'move' | 'range';
export type Fill = 'natural' | 'mid';
export type PresetId = 'up' | 'up_moderate' | 'flat' | 'down_moderate' | 'down' | 'big_move';

export interface StructureTails {
  sigma_lo: number;
  sigma_hi: number;
  mass_lo: number;
  mass_hi: number;
  location: number;
}

export interface StructureView {
  preset: PresetId | null;
  lo: number | null;
  hi: number | null;
  outside: boolean;
  lo_moneyness: number | null;
  hi_moneyness: number | null;
  prob: number;
  prob_market: number;
}

export interface StructureRow {
  kind: StructureKind;
  direction: StructureDirection;
  legs: string;
  strikes: number[];
  net_premium: number;
  max_loss: number;
  max_gain: number | null;
  breakevens: number[];
  prob_profit: number;
  expected_return: number;
  annualised_return: number | null;
  reward_to_risk: number | null;
  prob_profit_given_view: number | null;
  return_if_right: number | null;
  return_if_wrong: number | null;
  worst_in_view: number;
  pnl_std: number;
  tail_share: number;
}

export interface StructureKindBest extends StructureRow {
  /** P&L over max loss at each grid price. */
  curve: number[];
}

export interface DominanceSegment {
  from: number;
  to: number;
  kind: StructureKind;
}

export interface StructureVerdict {
  best_kind: StructureKind | null;
  spread_kind: StructureKind | null;
  single_kind: StructureKind | null;
  spread_return_if_right: number | null;
  single_return_if_right: number | null;
  advantage: number | null;
  reason: string;
}

export interface StructuresResponse {
  symbol: string;
  session: IsoDate;
  expiration: IsoDate;
  dte_days: number;
  years: number;
  underlying_close: number;
  forward: number | null;
  fill: Fill;
  map_id: string;
  map_is_identity: boolean;
  look_ahead: boolean;
  tails: StructureTails;
  view: StructureView;
  grid: number[];
  density: number[];
  kinds: StructureKindBest[];
  ranking: StructureRow[];
  dominance: DominanceSegment[];
  verdict: StructureVerdict;
  n_structures: number;
  n_qualifying: number;
}

export interface OutcomePreset {
  id: PresetId;
  label: string;
}

export interface OutcomeCell {
  preset: PresetId;
  lo: number | null;
  hi: number | null;
  prob: number;
  prob_market: number;
  best_kind: StructureKind | null;
  best_return_if_right: number | null;
  best_legs: string | null;
  spread_kind: StructureKind | null;
  spread_return_if_right: number | null;
  single_kind: StructureKind | null;
  single_return_if_right: number | null;
  advantage: number | null;
}

export interface OutcomeRow {
  symbol: string;
  expiration: IsoDate | null;
  dte_days: number | null;
  underlying_close: number | null;
  cells: OutcomeCell[];
  unavailable_reason?: string | null;
}

export interface OutcomeMapResponse {
  session: IsoDate;
  target_dte: number;
  fill: Fill;
  map_id: string;
  presets: OutcomePreset[];
  rows: OutcomeRow[];
}

/** Request sent to `GET /api/structures/{symbol}/{session}`. */
export interface StructureQuery {
  symbol: string;
  session: IsoDate;
  /** Null lets the API pick the expiration nearest 35 days. */
  expiration: IsoDate | null;
  /** A preset, or null for the custom bounds below. */
  preset: PresetId | null;
  /** Bounds as a fraction of the close (1.05 is 5% above); null is open. */
  lo: number | null;
  hi: number | null;
  outside: boolean;
  fill: Fill;
  map: MapChoice;
  /** Smallest P(profit | view) for a structure to qualify, in [0, 1]. */
  minPopGiven: number;
}

/** Request sent to `GET /api/structures/map`. */
export interface OutcomeMapQuery {
  session: IsoDate | 'latest';
  targetDte: number;
  fill: Fill;
  map: MapChoice;
  minPopGiven: number;
}
