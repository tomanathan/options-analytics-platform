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
}
