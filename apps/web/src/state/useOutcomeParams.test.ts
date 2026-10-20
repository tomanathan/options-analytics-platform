import { act, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { parseOutcomeParams, useOutcomeParams } from './useOutcomeParams';

function setup(entry: string) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      MemoryRouter,
      { initialEntries: [entry], future: { v7_startTransition: true, v7_relativeSplatPath: true } },
      children,
    );
  return renderHook(() => ({ ...useOutcomeParams(), search: useLocation().search }), { wrapper });
}

describe('parseOutcomeParams', () => {
  it('defaults to the latest session, 35 days, natural fill, auto map and a 50% floor', () => {
    expect(parseOutcomeParams(new URLSearchParams())).toEqual({
      session: 'latest',
      targetDte: 35,
      fill: 'natural',
      map: 'auto',
      minPop: 0.5,
    });
  });

  it('clamps the target DTE to 7 to 120 and ignores a malformed session', () => {
    expect(parseOutcomeParams(new URLSearchParams('dte=400&session=yesterday'))).toMatchObject({
      session: 'latest',
      targetDte: 120,
    });
    expect(parseOutcomeParams(new URLSearchParams('dte=2')).targetDte).toBe(7);
  });
});

describe('useOutcomeParams', () => {
  it('writes non-default values and drops defaults', () => {
    const { result } = setup('/outcomes');
    act(() => result.current.update({ targetDte: 60, fill: 'mid', session: '2026-10-01' }));
    expect(result.current.search).toBe('?session=2026-10-01&dte=60&fill=mid');
    expect(result.current.query).toEqual({
      session: '2026-10-01',
      targetDte: 60,
      fill: 'mid',
      map: 'auto',
      minPopGiven: 0.5,
    });
    act(() => result.current.update({ targetDte: 35, fill: 'natural', session: 'latest' }));
    expect(result.current.search).toBe('');
  });
});
