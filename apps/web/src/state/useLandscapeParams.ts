import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { IsoDate, MapChoice } from '../api/types';
import type { Layout, View, XMode } from '../charts/options';
import { nearestEarlierIndex } from '../lib/sessions';

export const DEFAULT_UNDERLYING = 'SPY';

const MAPS: readonly MapChoice[] = ['auto', 'production', 'walk_forward'];
const VIEWS: readonly View[] = ['raw', 'calibrated', 'both'];
const LAYOUTS: readonly Layout[] = ['multiples', 'overlay'];
const XMODES: readonly XMode[] = ['moneyness', 'strike'];

export interface LandscapeParams {
  u: string;
  /** The session on screen; null until the session list is known. */
  d: IsoDate | null;
  /** Index of `d` in the session list, or -1 when unknown. */
  index: number;
  map: MapChoice;
  view: View;
  layout: Layout;
  x: XMode;
  /** Expiry chosen for the chain table; null means the first expiry. */
  exp: IsoDate | null;
}

export type LandscapePatch = Partial<Omit<LandscapeParams, 'index'>>;

const DEFAULTS = {
  u: DEFAULT_UNDERLYING,
  map: 'auto' as MapChoice,
  view: 'both' as View,
  layout: 'multiples' as Layout,
  x: 'moneyness' as XMode,
};

function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.find((item) => item === value) ?? fallback;
}

/**
 * Landscape state lives in the URL. `d` resolves against the loaded session list: absent means
 * the latest session, a date that is not a session means the nearest earlier one. Keeping `d`
 * across an underlying switch therefore lands on the nearest earlier session of the new one.
 */
export function useLandscapeParams(sessionDates: readonly IsoDate[] | undefined) {
  const [search, setSearch] = useSearchParams();

  const params = useMemo<LandscapeParams>(() => {
    const rawDate = search.get('d');
    let d: IsoDate | null = rawDate;
    let index = -1;
    if (sessionDates && sessionDates.length > 0) {
      index =
        rawDate === null ? sessionDates.length - 1 : nearestEarlierIndex(sessionDates, rawDate);
      d = sessionDates[index] ?? null;
    } else {
      d = null;
    }
    return {
      u: search.get('u') ?? DEFAULTS.u,
      d,
      index,
      map: pick(search.get('map'), MAPS, DEFAULTS.map),
      view: pick(search.get('view'), VIEWS, DEFAULTS.view),
      layout: pick(search.get('layout'), LAYOUTS, DEFAULTS.layout),
      x: pick(search.get('x'), XMODES, DEFAULTS.x),
      exp: search.get('exp'),
    };
  }, [search, sessionDates]);

  const update = useCallback(
    (patch: LandscapePatch, options: { replace?: boolean } = {}) => {
      setSearch(
        (previous) => {
          const next = new URLSearchParams(previous);
          const write = (key: string, value: string | null, fallback?: string) => {
            if (value === null || value === fallback) next.delete(key);
            else next.set(key, value);
          };
          if ('u' in patch && patch.u !== undefined) write('u', patch.u, DEFAULTS.u);
          if ('d' in patch) write('d', patch.d ?? null);
          if (patch.map !== undefined) write('map', patch.map, DEFAULTS.map);
          if (patch.view !== undefined) write('view', patch.view, DEFAULTS.view);
          if (patch.layout !== undefined) write('layout', patch.layout, DEFAULTS.layout);
          if (patch.x !== undefined) write('x', patch.x, DEFAULTS.x);
          if ('exp' in patch) write('exp', patch.exp ?? null);
          return next;
        },
        { replace: options.replace ?? false },
      );
    },
    [setSearch],
  );

  return { params, update };
}
