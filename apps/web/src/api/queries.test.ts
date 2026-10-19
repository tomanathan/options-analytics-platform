import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import {
  isSessionReady,
  MAX_BUSY_RETRIES,
  paths,
  qk,
  retryDelayMs,
  shouldRetry,
  spreadSearchParams,
} from './queries';
import type { SpreadQuery } from './types';

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
    });
    expect(params.getAll('underlying')).toEqual(['SPY', 'XLF']);
    expect(params.get('min_width')).toBe('2.5');
    expect(params.has('max_width')).toBe(false);
    expect(params.get('eligible_only')).toBe('false');
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
