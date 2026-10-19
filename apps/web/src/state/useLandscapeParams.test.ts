import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { DEFAULT_UNDERLYING, useLandscapeParams } from './useLandscapeParams';

const SPY_DATES = ['2026-09-24', '2026-09-25', '2026-09-28', '2026-10-02'];
const XLF_DATES = ['2026-09-25', '2026-09-29', '2026-10-01'];

function setup(entry: string, dates: readonly string[] | undefined) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      MemoryRouter,
      { initialEntries: [entry], future: { v7_startTransition: true, v7_relativeSplatPath: true } },
      children,
    );
  return renderHook(
    ({ list }: { list: readonly string[] | undefined }) => {
      const landscape = useLandscapeParams(list);
      const location = useLocation();
      return { ...landscape, search: location.search };
    },
    { wrapper, initialProps: { list: dates } },
  );
}

describe('useLandscapeParams', () => {
  it('defaults to SPY and the latest session', () => {
    const { result } = setup('/landscape', SPY_DATES);
    expect(result.current.params).toMatchObject({
      u: DEFAULT_UNDERLYING,
      d: '2026-10-02',
      index: 3,
      map: 'auto',
      view: 'both',
      layout: 'multiples',
      x: 'moneyness',
      exp: null,
    });
  });

  it('has no session until the list is known', () => {
    const { result } = setup('/landscape?d=2026-09-28', undefined);
    expect(result.current.params.d).toBeNull();
    expect(result.current.params.index).toBe(-1);
  });

  it('resolves a date that is not a session to the nearest earlier one', () => {
    const { result } = setup('/landscape?d=2026-10-01', SPY_DATES);
    expect(result.current.params.d).toBe('2026-09-28');
    expect(result.current.params.index).toBe(2);
  });

  it('uses the first session when the date precedes them all', () => {
    const { result } = setup('/landscape?d=2020-01-01', SPY_DATES);
    expect(result.current.params.index).toBe(0);
  });

  it('keeps d on an underlying switch and lands on the nearest earlier session of the new list', () => {
    const { result, rerender } = setup('/landscape?d=2026-09-28', SPY_DATES);
    expect(result.current.params.d).toBe('2026-09-28');

    act(() => result.current.update({ u: 'XLF' }));
    expect(result.current.params.u).toBe('XLF');
    expect(result.current.search).toContain('d=2026-09-28');
    // The list of the new underlying arrives; d resolves against it.
    rerender({ list: XLF_DATES });
    expect(result.current.params.d).toBe('2026-09-25');
    expect(result.current.params.index).toBe(0);
  });

  it('writes non-default values to the URL and drops defaults', () => {
    const { result } = setup('/landscape', SPY_DATES);
    act(() => result.current.update({ map: 'production', view: 'calibrated', x: 'strike' }));
    expect(result.current.search).toBe('?map=production&view=calibrated&x=strike');
    act(() => result.current.update({ map: 'auto', u: 'SPY' }));
    expect(result.current.search).toBe('?view=calibrated&x=strike');
  });

  it('writes d on a seek and ignores invalid enum values', () => {
    const { result } = setup('/landscape?map=bogus&view=nope', SPY_DATES);
    expect(result.current.params.map).toBe('auto');
    expect(result.current.params.view).toBe('both');
    act(() => result.current.update({ d: '2026-09-25' }, { replace: true }));
    expect(result.current.params.d).toBe('2026-09-25');
    expect(result.current.search).toContain('d=2026-09-25');
  });
});
