import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type {
  Fill,
  IsoDate,
  MapChoice,
  PresetId,
  StructureKind,
  StructureQuery,
} from '../api/types';
import { nearestEarlierIndex } from '../lib/sessions';
import { KIND_ORDER, PRESET_IDS } from '../lib/structures';
import { DEFAULT_UNDERLYING } from './useLandscapeParams';

export const DEFAULT_PRESET: PresetId = 'up_moderate';
export const DEFAULT_FILL: Fill = 'natural';
export const DEFAULT_MAP: MapChoice = 'auto';
/** Default floor on P(profit | view) for a structure to qualify. */
export const DEFAULT_MIN_POP = 0.5;
export const MAX_MIN_POP = 0.9;

const FILLS: readonly Fill[] = ['natural', 'mid'];
const MAPS: readonly MapChoice[] = ['auto', 'production', 'walk_forward'];

export interface StructureParams {
  symbol: string;
  /** The session on screen; null until the session list is known. */
  session: IsoDate | null;
  /** Null lets the API pick the expiration nearest 35 days. */
  expiration: IsoDate | null;
  /** A preset, or null when the view is the custom range below. */
  preset: PresetId | null;
  /** Custom bounds as a fraction of the close (1.05 is 5% above); null is open. */
  lo: number | null;
  hi: number | null;
  outside: boolean;
  fill: Fill;
  map: MapChoice;
  /** Selected kind; null means the verdict's best kind. */
  kind: StructureKind | null;
  minPop: number;
}

export type StructurePatch = Partial<StructureParams>;

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return allowed.find((item) => item === value) ?? null;
}

function bound(value: string | null): number | null {
  if (value === null || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function probability(value: string | null): number {
  if (value === null || value.trim() === '') return DEFAULT_MIN_POP;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(MAX_MIN_POP, Math.max(0, parsed)) : DEFAULT_MIN_POP;
}

/**
 * Read the structures state from the URL (`symbol, session, expiration, preset, lo, hi, outside,
 * fill, map, kind, minPop`). A preset wins over bounds; with neither, the default preset applies.
 * `session` resolves against the session list as on the landscape page: absent is the latest,
 * a date that is not a session is the nearest earlier one.
 */
export function parseStructureParams(
  search: URLSearchParams,
  sessionDates: readonly IsoDate[] | undefined,
): StructureParams {
  const rawSession = search.get('session');
  let session: IsoDate | null = null;
  if (sessionDates && sessionDates.length > 0) {
    const index =
      rawSession === null ? sessionDates.length - 1 : nearestEarlierIndex(sessionDates, rawSession);
    session = sessionDates[index] ?? null;
  }
  const lo = bound(search.get('lo'));
  const hi = bound(search.get('hi'));
  const named = pick(search.get('preset'), PRESET_IDS);
  const custom = named === null && (lo !== null || hi !== null);
  return {
    symbol: search.get('symbol') ?? DEFAULT_UNDERLYING,
    session,
    expiration: search.get('expiration'),
    preset: custom ? null : (named ?? DEFAULT_PRESET),
    lo: custom ? lo : null,
    hi: custom ? hi : null,
    outside: custom && search.get('outside') === 'true',
    fill: pick(search.get('fill'), FILLS) ?? DEFAULT_FILL,
    map: pick(search.get('map'), MAPS) ?? DEFAULT_MAP,
    kind: pick(search.get('kind'), KIND_ORDER),
    minPop: probability(search.get('minPop')),
  };
}

/** The request the state describes; null until the session is known. */
export function toStructureQuery(params: StructureParams): StructureQuery | null {
  if (params.session === null) return null;
  return {
    symbol: params.symbol,
    session: params.session,
    expiration: params.expiration,
    preset: params.preset,
    lo: params.lo,
    hi: params.hi,
    outside: params.outside,
    fill: params.fill,
    map: params.map,
    minPopGiven: params.minPop,
  };
}

/** Structures state lives in the URL, written like the landscape page's (defaults dropped). */
export function useStructureParams(sessionDates: readonly IsoDate[] | undefined) {
  const [search, setSearch] = useSearchParams();
  const params = useMemo(() => parseStructureParams(search, sessionDates), [search, sessionDates]);
  const query = useMemo(() => toStructureQuery(params), [params]);

  const update = useCallback(
    (patch: StructurePatch, options: { replace?: boolean } = {}) => {
      setSearch(
        (previous) => {
          const next = new URLSearchParams(previous);
          const write = (key: string, value: string | null, fallback?: string) => {
            if (value === null || value === fallback) next.delete(key);
            else next.set(key, value);
          };
          const symbol = previous.get('symbol') ?? DEFAULT_UNDERLYING;
          if (patch.symbol !== undefined && patch.symbol !== symbol) {
            write('symbol', patch.symbol, DEFAULT_UNDERLYING);
            // Expirations belong to one underlying's chain.
            next.delete('expiration');
          }
          if ('session' in patch) {
            write('session', patch.session ?? null);
            next.delete('expiration');
          }
          if ('expiration' in patch) write('expiration', patch.expiration ?? null);
          if ('preset' in patch) {
            if (patch.preset) {
              write('preset', patch.preset, DEFAULT_PRESET);
              ['lo', 'hi', 'outside'].forEach((key) => next.delete(key));
            } else {
              next.delete('preset');
            }
          }
          if ('lo' in patch) write('lo', patch.lo === null ? null : String(patch.lo));
          if ('hi' in patch) write('hi', patch.hi === null ? null : String(patch.hi));
          if (patch.outside !== undefined) write('outside', patch.outside ? 'true' : null);
          if (patch.fill !== undefined) write('fill', patch.fill, DEFAULT_FILL);
          if (patch.map !== undefined) write('map', patch.map, DEFAULT_MAP);
          if ('kind' in patch) write('kind', patch.kind ?? null);
          if (patch.minPop !== undefined)
            write('minPop', String(patch.minPop), String(DEFAULT_MIN_POP));
          return next;
        },
        { replace: options.replace ?? false },
      );
    },
    [setSearch],
  );

  return { params, query, update };
}

/** The `/structures` URL for a state, as the outcome map links to it. */
export function structuresHref(state: {
  symbol: string;
  session: IsoDate;
  expiration: IsoDate | null;
  preset: PresetId;
  fill: Fill;
  map: MapChoice;
  minPop?: number;
}): string {
  const params = new URLSearchParams();
  params.set('symbol', state.symbol);
  params.set('session', state.session);
  if (state.expiration) params.set('expiration', state.expiration);
  params.set('preset', state.preset);
  params.set('fill', state.fill);
  params.set('map', state.map);
  if (state.minPop !== undefined && state.minPop !== DEFAULT_MIN_POP)
    params.set('minPop', String(state.minPop));
  return `/structures?${params.toString()}`;
}
