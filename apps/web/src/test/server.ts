import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import type { Fill, MapChoice, PresetId, SpreadSort } from '../api/types';
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
import { makeOutcomeMap, makeStructures } from './structureFixtures';

const PRESETS: readonly PresetId[] = [
  'up',
  'up_moderate',
  'flat',
  'down_moderate',
  'down',
  'big_move',
];

function presetOf(value: string | null): PresetId | null {
  return PRESETS.find((preset) => preset === value) ?? null;
}

function fillOf(value: string | null): Fill {
  return value === 'mid' ? 'mid' : 'natural';
}

/** Every request URL the handlers have seen, cleared after each test. */
export const requestLog: string[] = [];

function mapOf(url: URL): MapChoice {
  const value = url.searchParams.get('map');
  return value === 'production' || value === 'walk_forward' ? value : 'auto';
}

const SORTS: readonly SpreadSort[] = [
  'return',
  'edge',
  'reward_to_risk',
  'kelly',
  'pop',
  'pop_gap',
  'entry',
];

function sortOf(value: string | null): SpreadSort {
  return SORTS.find((sort) => sort === value) ?? 'return';
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
        minEdgePct: num('min_edge_pct'),
        sort: sortOf(q.get('sort')),
        limit: num('limit'),
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
  http.get('/api/structures/map', ({ request }) => {
    requestLog.push(request.url);
    const q = new URL(request.url).searchParams;
    return HttpResponse.json(
      makeOutcomeMap({
        session: q.get('session') ?? 'latest',
        targetDte: Number(q.get('target_dte') ?? 35),
        fill: fillOf(q.get('fill')),
        map: mapOf(new URL(request.url)),
      }),
    );
  }),
  http.get('/api/structures/:symbol/:session', ({ request, params }) => {
    requestLog.push(request.url);
    const q = new URL(request.url).searchParams;
    const bound = (key: string) => (q.has(key) ? Number(q.get(key)) : null);
    const preset = presetOf(q.get('preset'));
    const lo = bound('lo');
    const hi = bound('hi');
    if (preset === null && lo === null && hi === null) {
      return HttpResponse.json(
        { detail: 'Give a preset or at least one bound.', code: 'view_required' },
        { status: 422 },
      );
    }
    if (preset === null && lo !== null && hi !== null && lo >= hi) {
      return HttpResponse.json(
        { detail: 'The lower bound must be below the upper bound.', code: 'view_invalid' },
        { status: 422 },
      );
    }
    return HttpResponse.json(
      makeStructures({
        symbol: String(params.symbol),
        session: String(params.session),
        expiration: q.get('expiration'),
        preset,
        lo,
        hi,
        outside: q.get('outside') === 'true',
        fill: fillOf(q.get('fill')),
        map: mapOf(new URL(request.url)),
        minPopGiven: Number(q.get('min_pop_given') ?? 0.5),
      }),
    );
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
