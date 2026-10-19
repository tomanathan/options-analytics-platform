import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { MapChoice } from '../api/types';
import {
  CALIBRATION,
  makeChain,
  makeDistribution,
  makeHeatmap,
  makeSessions,
  makeSpreadDetail,
  makeSpreads,
  UNDERLYINGS,
} from './fixtures';

/** Every request URL the handlers have seen, cleared after each test. */
export const requestLog: string[] = [];

function mapOf(url: URL): MapChoice {
  const value = url.searchParams.get('map');
  return value === 'production' || value === 'walk_forward' ? value : 'auto';
}

export const handlers = [
  http.get('/api/underlyings', ({ request }) => {
    requestLog.push(request.url);
    return HttpResponse.json(UNDERLYINGS);
  }),
  http.get('/api/underlyings/:symbol/sessions', ({ request, params }) => {
    requestLog.push(request.url);
    return HttpResponse.json(makeSessions(String(params.symbol)));
  }),
  http.get('/api/underlyings/:symbol/sessions/:session/chain', ({ request, params }) => {
    requestLog.push(request.url);
    return HttpResponse.json(makeChain(String(params.session), String(params.symbol)));
  }),
  http.get('/api/underlyings/:symbol/sessions/:session/distribution', ({ request, params }) => {
    requestLog.push(request.url);
    return HttpResponse.json(
      makeDistribution(String(params.session), mapOf(new URL(request.url)), String(params.symbol)),
    );
  }),
  http.get('/api/underlyings/:symbol/sessions/:session/heatmap', ({ request, params }) => {
    requestLog.push(request.url);
    return HttpResponse.json(
      makeHeatmap(String(params.session), mapOf(new URL(request.url)), String(params.symbol)),
    );
  }),
  http.get('/api/spreads', ({ request }) => {
    requestLog.push(request.url);
    const q = new URL(request.url).searchParams;
    const num = (key: string) => (q.has(key) ? Number(q.get(key)) : null);
    return HttpResponse.json(
      makeSpreads({
        underlyings: q.getAll('underlying'),
        expiration: q.get('expiration'),
        minWidth: num('min_width'),
        maxWidth: num('max_width'),
        minPop: num('min_pop') ?? 0,
        minCredit: num('min_credit') ?? 0,
        eligibleOnly: q.get('eligible_only') !== 'false',
      }),
    );
  }),
  http.get('/api/spreads/:key', ({ request, params }) => {
    requestLog.push(request.url);
    const detail = makeSpreadDetail(decodeURIComponent(String(params.key)));
    return detail
      ? HttpResponse.json(detail)
      : HttpResponse.json({ detail: 'Unknown spread', code: 'not_found' }, { status: 404 });
  }),
  http.get('/api/calibration/summary', ({ request }) => {
    requestLog.push(request.url);
    return HttpResponse.json(CALIBRATION);
  }),
];

export const server = setupServer(...handlers);

/** A 503 `database_busy` response with a `Retry-After` header. */
export function busyResponse(retryAfter = 15) {
  return HttpResponse.json(
    {
      detail: 'The DuckDB file is locked by a writer (dbt_build or score_spreads). Retry shortly.',
      code: 'database_busy',
    },
    { status: 503, headers: { 'Retry-After': String(retryAfter) } },
  );
}
