import { keepPreviousData, QueryClient, useQuery } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import { ApiError, DEFAULT_RETRY_AFTER_S, fetchJson } from './client';
import type {
  CalibrationSummary,
  ChainResponse,
  DistributionResponse,
  HeatmapResponse,
  IsoDate,
  MapChoice,
  SessionsResponse,
  SpreadDetail,
  SpreadQuery,
  SpreadsResponse,
  UnderlyingsResponse,
} from './types';

/** Busy retries stop after this many attempts. */
export const MAX_BUSY_RETRIES = 8;
/** The wait between busy retries never exceeds this many seconds. */
export const MAX_RETRY_DELAY_S = 30;

export function isBusyError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 503 && error.code === 'database_busy';
}

/** Retry only a busy database (503 `database_busy`), at most `MAX_BUSY_RETRIES` times. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  return isBusyError(error) && failureCount < MAX_BUSY_RETRIES;
}

/** Wait `Retry-After` seconds (capped at 30 s) before the next busy retry, in milliseconds. */
export function retryDelayMs(_failureCount: number, error: unknown): number {
  const seconds = error instanceof ApiError ? (error.retryAfterS ?? DEFAULT_RETRY_AFTER_S) : 0;
  return Math.min(seconds, MAX_RETRY_DELAY_S) * 1000;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        retryDelay: retryDelayMs,
        refetchOnWindowFocus: false,
        placeholderData: keepPreviousData,
      },
    },
  });
}

/** URL paths for every endpoint; the single place that knows the route shapes. */
export const paths = {
  underlyings: () => '/api/underlyings',
  sessions: (symbol: string) => `/api/underlyings/${encodeURIComponent(symbol)}/sessions`,
  chain: (symbol: string, session: IsoDate) => `${paths.sessions(symbol)}/${session}/chain`,
  distribution: (symbol: string, session: IsoDate, map: MapChoice) =>
    `${paths.sessions(symbol)}/${session}/distribution?map=${map}`,
  heatmap: (symbol: string, session: IsoDate, map: MapChoice) =>
    `${paths.sessions(symbol)}/${session}/heatmap?map=${map}`,
  spreads: (query: SpreadQuery) => `/api/spreads?${spreadSearchParams(query).toString()}`,
  spread: (key: string) => `/api/spreads/${encodeURIComponent(key)}`,
  calibration: () => '/api/calibration/summary',
};

export function spreadSearchParams(query: SpreadQuery): URLSearchParams {
  const params = new URLSearchParams();
  query.underlying.forEach((symbol) => params.append('underlying', symbol));
  if (query.expiration) params.set('expiration', query.expiration);
  if (query.minWidth !== null) params.set('min_width', String(query.minWidth));
  if (query.maxWidth !== null) params.set('max_width', String(query.maxWidth));
  params.set('min_pop', String(query.minPop));
  params.set('min_credit', String(query.minCredit));
  params.set('eligible_only', String(query.eligibleOnly));
  return params;
}

/** Query-key factory. Keys are plain tuples so `getQueryData` and `prefetchQuery` agree. */
export const qk = {
  underlyings: () => ['underlyings'] as const,
  sessions: (symbol: string) => ['sessions', symbol] as const,
  chain: (symbol: string, session: IsoDate) => ['chain', symbol, session] as const,
  distribution: (symbol: string, session: IsoDate, map: MapChoice) =>
    ['distribution', symbol, session, map] as const,
  heatmap: (symbol: string, session: IsoDate, map: MapChoice) =>
    ['heatmap', symbol, session, map] as const,
  spreads: (query: SpreadQuery) => ['spreads', query] as const,
  spread: (key: string) => ['spread', key] as const,
  calibration: () => ['calibration'] as const,
};

/** Session data never changes for a given database signature, so it is never refetched. */
const SESSION_STALE_TIME = Infinity;
/** Tables that dbt rewrites are re-checked after a minute. */
const TABLE_STALE_TIME = 60_000;

export function useUnderlyings() {
  return useQuery({
    queryKey: qk.underlyings(),
    queryFn: ({ signal }) => fetchJson<UnderlyingsResponse>(paths.underlyings(), signal),
    staleTime: TABLE_STALE_TIME,
  });
}

export function useSessions(symbol: string) {
  return useQuery({
    queryKey: qk.sessions(symbol),
    queryFn: ({ signal }) => fetchJson<SessionsResponse>(paths.sessions(symbol), signal),
    staleTime: SESSION_STALE_TIME,
  });
}

export function useChain(symbol: string, session: IsoDate | null) {
  return useQuery({
    queryKey: qk.chain(symbol, session ?? ''),
    queryFn: ({ signal }) => fetchJson<ChainResponse>(paths.chain(symbol, session ?? ''), signal),
    enabled: session !== null,
    staleTime: SESSION_STALE_TIME,
  });
}

export function useDistribution(symbol: string, session: IsoDate | null, map: MapChoice) {
  return useQuery({
    queryKey: qk.distribution(symbol, session ?? '', map),
    queryFn: ({ signal }) =>
      fetchJson<DistributionResponse>(paths.distribution(symbol, session ?? '', map), signal),
    enabled: session !== null,
    staleTime: SESSION_STALE_TIME,
  });
}

export function useHeatmap(symbol: string, session: IsoDate | null, map: MapChoice) {
  return useQuery({
    queryKey: qk.heatmap(symbol, session ?? '', map),
    queryFn: ({ signal }) =>
      fetchJson<HeatmapResponse>(paths.heatmap(symbol, session ?? '', map), signal),
    enabled: session !== null,
    staleTime: SESSION_STALE_TIME,
  });
}

export function useSpreads(query: SpreadQuery) {
  return useQuery({
    queryKey: qk.spreads(query),
    queryFn: ({ signal }) => fetchJson<SpreadsResponse>(paths.spreads(query), signal),
    staleTime: TABLE_STALE_TIME,
  });
}

export function useSpreadDetail(key: string | null) {
  return useQuery({
    queryKey: qk.spread(key ?? ''),
    queryFn: ({ signal }) => fetchJson<SpreadDetail>(paths.spread(key ?? ''), signal),
    enabled: key !== null,
    staleTime: TABLE_STALE_TIME,
  });
}

export function useCalibrationSummary() {
  return useQuery({
    queryKey: qk.calibration(),
    queryFn: ({ signal }) => fetchJson<CalibrationSummary>(paths.calibration(), signal),
    staleTime: TABLE_STALE_TIME,
  });
}

/** The first busy (503 `database_busy`) failure among queries that are retrying, if any. */
export function busyError(...queries: UseQueryResult<unknown>[]): ApiError | null {
  for (const query of queries) {
    if (isBusyError(query.failureReason) && query.fetchStatus === 'fetching') {
      return query.failureReason;
    }
  }
  return null;
}

/** First terminal (non-busy) error among queries, if any. */
export function terminalError(...queries: UseQueryResult<unknown>[]): ApiError | Error | null {
  for (const query of queries) {
    if (query.isError) return query.error;
  }
  return null;
}

/** True when chain, distribution and heatmap for the session are all in the cache (playback gate). */
export function isSessionReady(
  client: QueryClient,
  symbol: string,
  session: IsoDate,
  map: MapChoice,
): boolean {
  return (
    client.getQueryData(qk.chain(symbol, session)) !== undefined &&
    client.getQueryData(qk.distribution(symbol, session, map)) !== undefined &&
    client.getQueryData(qk.heatmap(symbol, session, map)) !== undefined
  );
}

/** Warm the cache with the three per-session payloads (no-op for anything already cached). */
export function prefetchSession(
  client: QueryClient,
  symbol: string,
  session: IsoDate,
  map: MapChoice,
): void {
  const options = { staleTime: SESSION_STALE_TIME, retry: shouldRetry, retryDelay: retryDelayMs };
  void client.prefetchQuery({
    queryKey: qk.chain(symbol, session),
    queryFn: ({ signal }) => fetchJson<ChainResponse>(paths.chain(symbol, session), signal),
    ...options,
  });
  void client.prefetchQuery({
    queryKey: qk.distribution(symbol, session, map),
    queryFn: ({ signal }) =>
      fetchJson<DistributionResponse>(paths.distribution(symbol, session, map), signal),
    ...options,
  });
  void client.prefetchQuery({
    queryKey: qk.heatmap(symbol, session, map),
    queryFn: ({ signal }) =>
      fetchJson<HeatmapResponse>(paths.heatmap(symbol, session, map), signal),
    ...options,
  });
}
