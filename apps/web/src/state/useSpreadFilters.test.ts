import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { parseSpreadFilters, toSpreadQuery, useSpreadFilters } from './useSpreadFilters';

function setup(entry: string) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      MemoryRouter,
      { initialEntries: [entry], future: { v7_startTransition: true, v7_relativeSplatPath: true } },
      children,
    );
  return renderHook(
    () => {
      const state = useSpreadFilters();
      return { ...state, search: useLocation().search };
    },
    { wrapper },
  );
}

describe('parseSpreadFilters', () => {
  it('defaults to the return ranking and no edge floor', () => {
    const filters = parseSpreadFilters(new URLSearchParams(''));
    expect(filters.rankBy).toBe('return');
    expect(filters.minEdgePct).toBeNull();
    expect(toSpreadQuery(filters)).toMatchObject({ sort: 'return', minEdgePct: null, limit: null });
  });

  it('reads by and edge from the URL', () => {
    const filters = parseSpreadFilters(new URLSearchParams('by=edge&edge=0.3'));
    expect(filters.rankBy).toBe('edge');
    expect(filters.minEdgePct).toBe(0.3);
    expect(toSpreadQuery(filters)).toMatchObject({ sort: 'edge', minEdgePct: 0.3 });
  });

  it.each(['return', 'edge', 'reward_to_risk', 'kelly', 'pop', 'pop_gap', 'entry'])(
    'accepts by=%s',
    (by) => {
      expect(parseSpreadFilters(new URLSearchParams({ by })).rankBy).toBe(by);
    },
  );

  it('falls back to return for an unknown ranking and ignores a non-numeric edge', () => {
    const filters = parseSpreadFilters(new URLSearchParams('by=hunch&edge=lots'));
    expect(filters.rankBy).toBe('return');
    expect(filters.minEdgePct).toBeNull();
  });
});

describe('useSpreadFilters', () => {
  it('round-trips by and edge through the URL', () => {
    const { result } = setup('/spreads?by=reward_to_risk&edge=0.25');
    expect(result.current.filters).toMatchObject({ rankBy: 'reward_to_risk', minEdgePct: 0.25 });

    act(() => result.current.update({ rankBy: 'pop_gap', minEdgePct: 0.1 }));
    expect(new URLSearchParams(result.current.search).get('by')).toBe('pop_gap');
    expect(new URLSearchParams(result.current.search).get('edge')).toBe('0.1');
    expect(result.current.filters).toMatchObject({ rankBy: 'pop_gap', minEdgePct: 0.1 });
    expect(result.current.query).toMatchObject({ sort: 'pop_gap', minEdgePct: 0.1 });
  });

  it('omits by when it is the default and edge when it is cleared', () => {
    const { result } = setup('/spreads?by=edge&edge=0.3&u=SPY');
    act(() => result.current.update({ rankBy: 'return', minEdgePct: null }));
    const search = new URLSearchParams(result.current.search);
    expect(search.has('by')).toBe(false);
    expect(search.has('edge')).toBe(false);
    expect(search.get('u')).toBe('SPY');
  });
});
