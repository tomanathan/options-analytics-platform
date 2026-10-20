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
 * Structures (`/api/structures`). Returns are per dollar of max loss (1.74 is 1.74x); a NaN on
 * the server (no mass inside or outside the view) arrives as null.
 */
export type StructuresResponse = Schemas['StructuresResponse'];
export type StructureKindBest = Schemas['KindBest'];
export type StructureRow = Schemas['StructureRow'];
export type StructureView = Schemas['ViewInfo'];
export type StructureTails = Schemas['TailInfo'];
export type StructureVerdict = Schemas['Verdict'];
export type DominanceSegment = Schemas['DominanceSegment'];
export type OutcomeMapResponse = Schemas['OutcomeMapResponse'];
export type OutcomePreset = Schemas['PresetInfo'];
export type OutcomeRow = Schemas['OutcomeRow'];
export type OutcomeCell = Schemas['OutcomeCell'];

export type StructureKind = StructureRow['kind'];
export type StructureDirection = StructureRow['direction'];
export type Fill = StructuresResponse['fill'];
export type PresetId = OutcomePreset['id'];

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
