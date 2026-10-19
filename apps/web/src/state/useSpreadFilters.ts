import { useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { IsoDate, SpreadQuery } from '../api/types';
import { assignSlots } from '../lib/colors';
import type { SeriesSlot } from '../lib/colors';

export const MAX_HIGHLIGHTS = 3;

export interface SpreadFilters {
  underlyings: string[];
  expiration: IsoDate | null;
  minWidth: number | null;
  maxWidth: number | null;
  minPop: number;
  minCredit: number;
  eligibleOnly: boolean;
  /** Explicit highlight list, or null to use the underlyings of the rank 1 to 3 rows. */
  highlights: string[] | null;
  selected: string | null;
}

function numberParam(value: string | null): number | null {
  if (value === null || value.trim() === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function listParam(value: string | null): string[] {
  return value ? value.split(',').filter((item) => item !== '') : [];
}

/** Read the filter state from the URL (`u, exp, wmin, wmax, pop, credit, elig, hl, sel`). */
export function parseSpreadFilters(search: URLSearchParams): SpreadFilters {
  return {
    underlyings: listParam(search.get('u')),
    expiration: search.get('exp'),
    minWidth: numberParam(search.get('wmin')),
    maxWidth: numberParam(search.get('wmax')),
    minPop: numberParam(search.get('pop')) ?? 0,
    minCredit: numberParam(search.get('credit')) ?? 0,
    eligibleOnly: search.get('elig') !== '0',
    highlights: search.has('hl') ? listParam(search.get('hl')).slice(0, MAX_HIGHLIGHTS) : null,
    selected: search.get('sel'),
  };
}

/** The request the filters describe. */
export function toSpreadQuery(filters: SpreadFilters): SpreadQuery {
  return {
    underlying: filters.underlyings,
    expiration: filters.expiration,
    minWidth: filters.minWidth,
    maxWidth: filters.maxWidth,
    minPop: filters.minPop,
    minCredit: filters.minCredit,
    eligibleOnly: filters.eligibleOnly,
  };
}

export function useSpreadFilters() {
  const [search, setSearch] = useSearchParams();
  const filters = useMemo(() => parseSpreadFilters(search), [search]);
  const query = useMemo(() => toSpreadQuery(filters), [filters]);

  const update = useCallback(
    (patch: Partial<SpreadFilters>, options: { replace?: boolean } = {}) => {
      setSearch(
        (previous) => {
          const next = new URLSearchParams(previous);
          const write = (key: string, value: string | null) => {
            if (value === null || value === '') next.delete(key);
            else next.set(key, value);
          };
          if (patch.underlyings !== undefined) write('u', patch.underlyings.join(','));
          if ('expiration' in patch) write('exp', patch.expiration ?? null);
          if ('minWidth' in patch)
            write(
              'wmin',
              patch.minWidth === null || patch.minWidth === undefined
                ? null
                : String(patch.minWidth),
            );
          if ('maxWidth' in patch)
            write(
              'wmax',
              patch.maxWidth === null || patch.maxWidth === undefined
                ? null
                : String(patch.maxWidth),
            );
          if (patch.minPop !== undefined)
            write('pop', patch.minPop > 0 ? String(patch.minPop) : null);
          if (patch.minCredit !== undefined)
            write('credit', patch.minCredit > 0 ? String(patch.minCredit) : null);
          if (patch.eligibleOnly !== undefined) write('elig', patch.eligibleOnly ? null : '0');
          if ('highlights' in patch) {
            if (patch.highlights === null || patch.highlights === undefined) next.delete('hl');
            else next.set('hl', patch.highlights.slice(0, MAX_HIGHLIGHTS).join(','));
          }
          if ('selected' in patch) write('sel', patch.selected ?? null);
          return next;
        },
        { replace: options.replace ?? false },
      );
    },
    [setSearch],
  );

  return { filters, query, update };
}

/** Highlight slots that stay with an underlying for as long as it remains highlighted. */
export function useHighlightSlots(
  highlights: readonly string[],
): { symbol: string; slot: SeriesSlot }[] {
  const previous = useRef<Record<string, SeriesSlot>>({});
  const slots = useMemo(() => assignSlots(previous.current, highlights), [highlights]);
  previous.current = slots;
  return useMemo(
    () =>
      highlights.flatMap((symbol) =>
        slots[symbol] === undefined ? [] : [{ symbol, slot: slots[symbol] }],
      ),
    [highlights, slots],
  );
}
