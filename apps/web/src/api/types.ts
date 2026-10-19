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
/**
 * Edge fields of the API (dollars per share unless stated). Declared here until the generated
 * schema carries them; the type then comes from `Schemas` alone.
 */
interface EdgeRowFields {
  fair_credit: number;
  edge: number;
  edge_natural: number;
  edge_pct: number;
  edge_pop: number;
  payoff_std: number;
  reward_to_risk: number | null;
  rank_edge: number | null;
  rank_rr: number | null;
  rank_entry: number | null;
  pop_implied: number;
  pop_gap: number;
  pop_gap_raw: number;
}
export type SpreadSort =
  'return' | 'edge' | 'reward_to_risk' | 'kelly' | 'pop' | 'pop_gap' | 'entry';
export type SpreadRow = Schemas['SpreadRow'] & EdgeRowFields;
export type SpreadsResponse = Omit<Schemas['SpreadsResponse'], 'rows'> & {
  rows: SpreadRow[];
  sort: SpreadSort;
  entry_rule: string;
};
export type SpreadDetail = Schemas['SpreadDetail'] &
  EdgeRowFields & { fair_credit_raw: number; edge_raw: number };
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
