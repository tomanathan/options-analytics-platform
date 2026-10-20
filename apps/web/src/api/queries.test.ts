import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import {
  ENTRY_QUERY,
  isSessionReady,
  MAX_BUSY_RETRIES,
  paths,
  qk,
  retryDelayMs,
  shouldRetry,
  spreadSearchParams,
  structureSearchParams,
} from './queries';
import type { SpreadQuery, StructureQuery } from './types';

const busy = new ApiError(503, 'locked', 'database_busy', 15);

describe('retry predicate', () => {
  it('retries a busy database up to the limit', () => {
    expect(shouldRetry(0, busy)).toBe(true);
    expect(shouldRetry(MAX_BUSY_RETRIES - 1, busy)).toBe(true);
    expect(shouldRetry(MAX_BUSY_RETRIES, busy)).toBe(false);
  });

  it('never retries other failures', () => {
    expect(shouldRetry(0, new ApiError(404, 'missing', 'not_found', null))).toBe(false);
    expect(shouldRetry(0, new ApiError(503, 'no file', 'database_missing', null))).toBe(false);
    expect(shouldRetry(0, new ApiError(500, 'boom', null, null))).toBe(false);
    expect(shouldRetry(0, new Error('network'))).toBe(false);
  });

  it('waits Retry-After seconds, capped at 30, defaulting to 15', () => {
    expect(retryDelayMs(0, busy)).toBe(15_000);
    expect(retryDelayMs(0, new ApiError(503, 'x', 'database_busy', 5))).toBe(5_000);
    expect(retryDelayMs(0, new ApiError(503, 'x', 'database_busy', 120))).toBe(30_000);
    expect(retryDelayMs(0, new ApiError(503, 'x', 'database_busy', null))).toBe(15_000);
  });
});

describe('query keys and paths', () => {
  it('builds equal keys for equal arguments and different keys for different ones', () => {
    expect(qk.distribution('SPY', '2026-10-02', 'auto')).toEqual(
      qk.distribution('SPY', '2026-10-02', 'auto'),
    );
    expect(qk.distribution('SPY', '2026-10-02', 'auto')).not.toEqual(
      qk.distribution('SPY', '2026-10-02', 'production'),
    );
    expect(qk.heatmap('SPY', '2026-10-02', 'auto')).not.toEqual(
      qk.distribution('SPY', '2026-10-02', 'auto'),
    );
  });

  it('hashes equal spread queries to the same cache entry', () => {
    const query: SpreadQuery = {
      underlying: ['SPY'],
      expiration: null,
      minWidth: null,
      maxWidth: null,
      minPop: 0,
      minCredit: 0,
      eligibleOnly: true,
      minEdgePct: null,
      sort: 'return',
      limit: null,
    };
    const client = new QueryClient();
    client.setQueryData(qk.spreads(query), { rows: [] });
    expect(client.getQueryData(qk.spreads({ ...query }))).toEqual({ rows: [] });
    expect(client.getQueryData(qk.spreads({ ...query, eligibleOnly: false }))).toBeUndefined();
  });

  it('encodes spread keys and repeats the underlying parameter', () => {
    expect(paths.spread('TSLA|2026-10-16|370|367.5')).toBe(
      '/api/spreads/TSLA%7C2026-10-16%7C370%7C367.5',
    );
    const params = spreadSearchParams({
      underlying: ['SPY', 'XLF'],
      expiration: '2026-10-16',
      minWidth: 2.5,
      maxWidth: null,
      minPop: 0.5,
      minCredit: 0,
      eligibleOnly: false,
      minEdgePct: null,
      sort: 'return',
      limit: null,
    });
    expect(params.getAll('underlying')).toEqual(['SPY', 'XLF']);
    expect(params.get('min_width')).toBe('2.5');
    expect(params.has('max_width')).toBe(false);
    expect(params.get('eligible_only')).toBe('false');
    expect(params.get('sort')).toBe('return');
    expect(params.has('min_edge_pct')).toBe(false);
    expect(params.has('limit')).toBe(false);
  });

  it('sends sort always, min_edge_pct and limit only when set', () => {
    const params = spreadSearchParams({
      ...ENTRY_QUERY,
      underlying: ['SPY'],
      minEdgePct: 0.2,
      sort: 'edge',
      limit: null,
    });
    expect(params.get('sort')).toBe('edge');
    expect(params.get('min_edge_pct')).toBe('0.2');
    expect(params.has('limit')).toBe(false);
  });

  it('asks for the entry list with a fixed query, whatever the filters', () => {
    const params = spreadSearchParams(ENTRY_QUERY);
    expect(params.get('sort')).toBe('entry');
    expect(params.get('limit')).toBe('10');
    expect(params.get('eligible_only')).toBe('true');
    expect(params.has('underlying')).toBe(false);
    expect(params.has('min_edge_pct')).toBe(false);
  });

  it('keys different sorts and edge floors separately', () => {
    const client = new QueryClient();
    client.setQueryData(qk.spreads(ENTRY_QUERY), { rows: [] });
    expect(client.getQueryData(qk.spreads({ ...ENTRY_QUERY, sort: 'edge' }))).toBeUndefined();
    expect(client.getQueryData(qk.spreads({ ...ENTRY_QUERY, minEdgePct: 0.1 }))).toBeUndefined();
    expect(client.getQueryData(qk.spreads({ ...ENTRY_QUERY }))).toEqual({ rows: [] });
  });
});

describe('structure paths', () => {
  const query: StructureQuery = {
    symbol: 'NVDA',
    session: '2026-10-16',
    expiration: null,
    preset: 'up_moderate',
    lo: null,
    hi: null,
    outside: false,
    fill: 'natural',
    map: 'auto',
    minPopGiven: 0.5,
  };

  it('sends a preset and leaves the expiration to the API when none is chosen', () => {
    const url = new URL(paths.structures(query), 'http://localhost');
    expect(url.pathname).toBe('/api/structures/NVDA/2026-10-16');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      preset: 'up_moderate',
      fill: 'natural',
      map: 'auto',
      min_pop_given: '0.5',
      limit: '25',
    });
  });

  it('sends the custom bounds, open ends left out, and outside only when set', () => {
    const params = structureSearchParams({
      ...query,
      expiration: '2026-11-20',
      preset: null,
      lo: 1.05,
      hi: null,
      outside: true,
    });
    expect(params.get('expiration')).toBe('2026-11-20');
    expect(params.has('preset')).toBe(false);
    expect(params.get('lo')).toBe('1.05');
    expect(params.has('hi')).toBe(false);
    expect(params.get('outside')).toBe('true');
  });

  it('keys structure and map queries by every parameter', () => {
    const client = new QueryClient();
    client.setQueryData(qk.structures(query), { kinds: [] });
    expect(client.getQueryData(qk.structures({ ...query }))).toEqual({ kinds: [] });
    expect(client.getQueryData(qk.structures({ ...query, fill: 'mid' }))).toBeUndefined();
    expect(
      paths.outcomeMap({
        session: 'latest',
        targetDte: 35,
        fill: 'mid',
        map: 'production',
        minPopGiven: 0.6,
      }),
    ).toBe(
      '/api/structures/map?session=latest&target_dte=35&fill=mid&map=production&min_pop_given=0.6',
    );
  });
});

describe('isSessionReady', () => {
  it('needs the chain, distribution and heatmap of the session in the cache', () => {
    const client = new QueryClient();
    expect(isSessionReady(client, 'SPY', '2026-10-02', 'auto')).toBe(false);
    client.setQueryData(qk.chain('SPY', '2026-10-02'), {});
    client.setQueryData(qk.distribution('SPY', '2026-10-02', 'auto'), {});
    expect(isSessionReady(client, 'SPY', '2026-10-02', 'auto')).toBe(false);
    client.setQueryData(qk.heatmap('SPY', '2026-10-02', 'auto'), {});
    expect(isSessionReady(client, 'SPY', '2026-10-02', 'auto')).toBe(true);
    expect(isSessionReady(client, 'SPY', '2026-10-02', 'production')).toBe(false);
  });
});
