import { renderHook, act } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server, busyResponse } from '../test/server';
import { UNDERLYINGS } from '../test/fixtures';
import { ApiError, fetchJson, getDataStatus, useDataStatus } from './client';
import type { UnderlyingsResponse } from './types';

describe('fetchJson', () => {
  it('parses a JSON body', async () => {
    const body = await fetchJson<UnderlyingsResponse>('/api/underlyings');
    expect(body.latest_session).toBe(UNDERLYINGS.latest_session);
    expect(body.underlyings.map((u) => u.symbol)).toEqual(['SPY', 'XLF']);
  });

  it('maps a 503 to an ApiError carrying the code and Retry-After seconds', async () => {
    server.use(http.get('/api/underlyings', () => busyResponse(15)));
    const error = await fetchJson('/api/underlyings').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const api = error as ApiError;
    expect(api.status).toBe(503);
    expect(api.code).toBe('database_busy');
    expect(api.retryAfterS).toBe(15);
    expect(api.message).toContain('locked by a writer');
  });

  it('reports a 404 with its code and no retry delay', async () => {
    server.use(
      http.get('/api/underlyings', () =>
        HttpResponse.json({ detail: 'Unknown symbol', code: 'not_found' }, { status: 404 }),
      ),
    );
    const error = (await fetchJson('/api/underlyings').catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(404);
    expect(error.code).toBe('not_found');
    expect(error.retryAfterS).toBeNull();
  });

  it('survives a non-JSON error body', async () => {
    server.use(
      http.get('/api/underlyings', () => new HttpResponse('Bad gateway', { status: 502 })),
    );
    const error = (await fetchJson('/api/underlyings').catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(502);
    expect(error.code).toBeNull();
  });

  it('updates the stale status from X-OAP-Data-Stale and clears it on a fresh response', async () => {
    const { result } = renderHook(() => useDataStatus());
    expect(result.current.stale).toBe(false);

    server.use(
      http.get('/api/underlyings', () =>
        HttpResponse.json(UNDERLYINGS, { headers: { 'X-OAP-Data-Stale': '1' } }),
      ),
    );
    await act(async () => {
      await fetchJson('/api/underlyings');
    });
    expect(getDataStatus().stale).toBe(true);
    expect(result.current.stale).toBe(true);

    server.resetHandlers();
    await act(async () => {
      await fetchJson('/api/underlyings');
    });
    expect(result.current.stale).toBe(false);
  });
});
