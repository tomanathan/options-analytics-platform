import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { Fill, IsoDate, MapChoice, OutcomeMapQuery } from '../api/types';
import { DEFAULT_FILL, DEFAULT_MAP, DEFAULT_MIN_POP, MAX_MIN_POP } from './useStructureParams';

export const DEFAULT_TARGET_DTE = 35;
export const MIN_TARGET_DTE = 7;
export const MAX_TARGET_DTE = 120;

const FILLS: readonly Fill[] = ['natural', 'mid'];
const MAPS: readonly MapChoice[] = ['auto', 'production', 'walk_forward'];

export interface OutcomeParams {
  /** A session date, or `latest`. */
  session: IsoDate | 'latest';
  targetDte: number;
  fill: Fill;
  map: MapChoice;
  minPop: number;
}

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.find((item) => item === value) ?? fallback;
}

function clamped(value: string | null, lo: number, hi: number, fallback: number): number {
  if (value === null || value.trim() === '') return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(hi, Math.max(lo, parsed)) : fallback;
}

/** Read the outcome-map state from the URL (`session, dte, fill, map, minPop`). */
export function parseOutcomeParams(search: URLSearchParams): OutcomeParams {
  const session = search.get('session');
  return {
    session: session && /^\d{4}-\d{2}-\d{2}$/.test(session) ? session : 'latest',
    targetDte: Math.round(
      clamped(search.get('dte'), MIN_TARGET_DTE, MAX_TARGET_DTE, DEFAULT_TARGET_DTE),
    ),
    fill: pick(search.get('fill'), FILLS, DEFAULT_FILL),
    map: pick(search.get('map'), MAPS, DEFAULT_MAP),
    minPop: clamped(search.get('minPop'), 0, MAX_MIN_POP, DEFAULT_MIN_POP),
  };
}

export function toOutcomeMapQuery(params: OutcomeParams): OutcomeMapQuery {
  return {
    session: params.session,
    targetDte: params.targetDte,
    fill: params.fill,
    map: params.map,
    minPopGiven: params.minPop,
  };
}

/** Outcome-map state lives in the URL; defaults are dropped from it. */
export function useOutcomeParams() {
  const [search, setSearch] = useSearchParams();
  const params = useMemo(() => parseOutcomeParams(search), [search]);
  const query = useMemo(() => toOutcomeMapQuery(params), [params]);

  const update = useCallback(
    (patch: Partial<OutcomeParams>) => {
      setSearch((previous) => {
        const next = new URLSearchParams(previous);
        const write = (key: string, value: string, fallback: string) => {
          if (value === fallback) next.delete(key);
          else next.set(key, value);
        };
        if (patch.session !== undefined) write('session', patch.session, 'latest');
        if (patch.targetDte !== undefined)
          write('dte', String(patch.targetDte), String(DEFAULT_TARGET_DTE));
        if (patch.fill !== undefined) write('fill', patch.fill, DEFAULT_FILL);
        if (patch.map !== undefined) write('map', patch.map, DEFAULT_MAP);
        if (patch.minPop !== undefined)
          write('minPop', String(patch.minPop), String(DEFAULT_MIN_POP));
        return next;
      });
    },
    [setSearch],
  );

  return { params, query, update };
}
