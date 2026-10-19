import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PREFETCH_AHEAD, usePlayback } from './usePlayback';

interface Harness {
  length?: number;
  stride?: number;
  fps?: number;
  start?: number;
  isReady?: (index: number) => boolean;
  prefetch?: (index: number) => void;
}

function useHarness({ length = 10, stride = 1, fps = 4, start = 0, isReady, prefetch }: Harness) {
  const [index, setIndex] = useState(start);
  const playback = usePlayback({
    length,
    index,
    setIndex,
    fps,
    stride,
    isReady: isReady ?? (() => true),
    prefetch,
  });
  return { index, ...playback };
}

const tick = (ms = 250) => act(() => vi.advanceTimersByTime(ms));

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('usePlayback', () => {
  it('advances by the stride every 1000/fps milliseconds', () => {
    const { result } = renderHook(() => useHarness({ stride: 2 }));
    act(() => result.current.play());
    tick();
    expect(result.current.index).toBe(2);
    tick();
    expect(result.current.index).toBe(4);
    expect(result.current.playing).toBe(true);
  });

  it('holds while the next frame is not ready, then resumes', () => {
    let ready = false;
    const { result } = renderHook(() => useHarness({ isReady: () => ready }));
    act(() => result.current.play());
    tick(1000);
    expect(result.current.index).toBe(0);
    expect(result.current.playing).toBe(true);
    ready = true;
    tick();
    expect(result.current.index).toBe(1);
  });

  it('stops at the end instead of looping', () => {
    const { result } = renderHook(() => useHarness({ length: 5, stride: 2 }));
    act(() => result.current.play());
    tick(250);
    tick(250);
    expect(result.current.index).toBe(4);
    expect(result.current.playing).toBe(false);
    tick(1000);
    expect(result.current.index).toBe(4);
  });

  it('clamps the last step to the final frame', () => {
    const { result } = renderHook(() => useHarness({ length: 4, stride: 3 }));
    act(() => result.current.play());
    tick(250);
    expect(result.current.index).toBe(3);
    expect(result.current.playing).toBe(false);
  });

  it('pauses on request', () => {
    const { result } = renderHook(() => useHarness({}));
    act(() => result.current.play());
    tick();
    expect(result.current.index).toBe(1);
    act(() => result.current.pause());
    tick(1000);
    expect(result.current.index).toBe(1);
    expect(result.current.playing).toBe(false);
  });

  it('starts over when played from the last frame', () => {
    const { result } = renderHook(() => useHarness({ length: 5, start: 4 }));
    act(() => result.current.play());
    expect(result.current.index).toBe(0);
    expect(result.current.playing).toBe(true);
  });

  it('runs at the requested frame rate', () => {
    const { result } = renderHook(() => useHarness({ fps: 8 }));
    act(() => result.current.play());
    tick(125);
    expect(result.current.index).toBe(1);
    tick(125);
    expect(result.current.index).toBe(2);
  });

  it('prefetches the next frames while playing, and not while paused', () => {
    const prefetch = vi.fn();
    const { result } = renderHook(() => useHarness({ prefetch, length: 20 }));
    expect(prefetch).not.toHaveBeenCalled();
    act(() => result.current.play());
    expect(prefetch.mock.calls.map((call) => call[0] as number)).toEqual(
      Array.from({ length: PREFETCH_AHEAD }, (_, k) => k + 1),
    );
  });

  it('does not prefetch beyond the last frame', () => {
    const prefetch = vi.fn();
    const { result } = renderHook(() => useHarness({ prefetch, length: 4 }));
    act(() => result.current.play());
    expect(prefetch.mock.calls.map((call) => call[0] as number)).toEqual([1, 2, 3]);
  });
});
