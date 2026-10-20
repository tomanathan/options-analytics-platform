import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { DEFAULT_UNDERLYING } from './useLandscapeParams';
import {
  DEFAULT_MIN_POP,
  DEFAULT_PRESET,
  parseStructureParams,
  structuresHref,
  toStructureQuery,
  useStructureParams,
} from './useStructureParams';

const DATES = ['2026-09-24', '2026-09-25', '2026-09-28', '2026-10-02'];

function setup(entry: string, dates: readonly string[] | undefined = DATES) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      MemoryRouter,
      { initialEntries: [entry], future: { v7_startTransition: true, v7_relativeSplatPath: true } },
      children,
    );
  return renderHook(
    ({ list }: { list: readonly string[] | undefined }) => {
      const state = useStructureParams(list);
      return { ...state, search: useLocation().search };
    },
    { wrapper, initialProps: { list: dates } },
  );
}

const parse = (search: string, ...dates: [readonly string[] | undefined] | []) =>
  parseStructureParams(new URLSearchParams(search), dates.length === 0 ? DATES : dates[0]);

describe('parseStructureParams', () => {
  it('defaults to SPY, the latest session, the default preset, natural fill and auto map', () => {
    expect(parse('')).toEqual({
      symbol: DEFAULT_UNDERLYING,
      session: '2026-10-02',
      expiration: null,
      preset: DEFAULT_PRESET,
      lo: null,
      hi: null,
      outside: false,
      fill: 'natural',
      map: 'auto',
      kind: null,
      minPop: DEFAULT_MIN_POP,
    });
  });

  it('has no session (and so no query) until the session list is known', () => {
    const params = parse('session=2026-09-28', undefined);
    expect(params.session).toBeNull();
    expect(toStructureQuery(params)).toBeNull();
  });

  it('resolves a date that is not a session to the nearest earlier one', () => {
    expect(parse('session=2026-10-01').session).toBe('2026-09-28');
  });

  it('reads custom bounds when no preset is given and lets a preset win over bounds', () => {
    expect(parse('lo=1.05&outside=true')).toMatchObject({
      preset: null,
      lo: 1.05,
      hi: null,
      outside: true,
    });
    expect(parse('preset=flat&lo=1.05&outside=true')).toMatchObject({
      preset: 'flat',
      lo: null,
      outside: false,
    });
  });

  it('ignores unknown enum values and clamps the probability floor', () => {
    expect(parse('preset=moon&fill=best&map=x&kind=collar&minPop=3')).toMatchObject({
      preset: DEFAULT_PRESET,
      fill: 'natural',
      map: 'auto',
      kind: null,
      minPop: 0.9,
    });
  });

  it('turns the state into the API request', () => {
    expect(toStructureQuery(parse('symbol=XLF&expiration=2026-11-20&fill=mid&minPop=0.6'))).toEqual(
      {
        symbol: 'XLF',
        session: '2026-10-02',
        expiration: '2026-11-20',
        preset: DEFAULT_PRESET,
        lo: null,
        hi: null,
        outside: false,
        fill: 'mid',
        map: 'auto',
        minPopGiven: 0.6,
      },
    );
  });
});

describe('useStructureParams', () => {
  it('drops defaults from the URL and writes the rest', () => {
    const { result } = setup('/structures');
    act(() => result.current.update({ fill: 'mid', preset: 'flat', minPop: 0.6 }));
    expect(result.current.search).toBe('?preset=flat&fill=mid&minPop=0.6');
    act(() => result.current.update({ fill: 'natural', preset: DEFAULT_PRESET, minPop: 0.5 }));
    expect(result.current.search).toBe('');
  });

  it('switches from a preset to a custom range and back', () => {
    const { result } = setup('/structures?preset=up');
    act(() => result.current.update({ preset: null, lo: 1.02, hi: 1.08, outside: false }));
    expect(result.current.params).toMatchObject({ preset: null, lo: 1.02, hi: 1.08 });
    expect(result.current.search).toBe('?lo=1.02&hi=1.08');
    act(() => result.current.update({ preset: 'big_move' }));
    expect(result.current.params).toMatchObject({ preset: 'big_move', lo: null, hi: null });
    expect(result.current.search).toBe('?preset=big_move');
  });

  it('forgets the expiration when the underlying or the session changes', () => {
    const { result } = setup('/structures?expiration=2026-11-20&kind=long_call');
    act(() => result.current.update({ symbol: 'SPY' }));
    expect(result.current.params.expiration).toBe('2026-11-20');
    act(() => result.current.update({ symbol: 'XLF' }));
    expect(result.current.params).toMatchObject({
      symbol: 'XLF',
      expiration: null,
      kind: 'long_call',
    });
    act(() => result.current.update({ expiration: '2026-10-23' }));
    act(() => result.current.update({ session: '2026-09-25' }));
    expect(result.current.params).toMatchObject({ session: '2026-09-25', expiration: null });
  });

  it('keeps the selected kind in the URL', () => {
    const { result } = setup('/structures');
    act(() => result.current.update({ kind: 'bull_call_spread' }, { replace: true }));
    expect(result.current.params.kind).toBe('bull_call_spread');
    expect(result.current.search).toBe('?kind=bull_call_spread');
  });
});

describe('structuresHref', () => {
  it('builds the link the outcome map uses', () => {
    expect(
      structuresHref({
        symbol: 'NVDA',
        session: '2026-10-16',
        expiration: '2026-11-20',
        preset: 'up',
        fill: 'mid',
        map: 'auto',
      }),
    ).toBe(
      '/structures?symbol=NVDA&session=2026-10-16&expiration=2026-11-20&preset=up&fill=mid&map=auto',
    );
  });
});
