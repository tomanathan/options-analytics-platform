import { useCallback, useEffect, useRef, useState } from 'react';

/** Frames per second at 1x speed. */
export const BASE_FPS = 4;
/** How many frames ahead of the current one are prefetched while playing. */
export const PREFETCH_AHEAD = 6;
/** Frames shown by a replay: pressing Play at the end rewinds this far, not to the first frame. */
export const REPLAY_FRAMES = 60;

export interface PlaybackOptions {
  /** Number of frames (positions) in the strided list. */
  length: number;
  /** Current frame position. */
  index: number;
  setIndex: (index: number) => void;
  fps: number;
  /** Frames advanced per tick. */
  stride: number;
  /** True when every query for the frame is cached; playback holds until it is. */
  isReady: (index: number) => boolean;
  /** Warm the cache for a frame; called for the next `PREFETCH_AHEAD` frames while playing. */
  prefetch?: (index: number) => void;
}

export interface Playback {
  playing: boolean;
  /** True when the current frame is the last one, so the next Play is a replay. */
  atEnd: boolean;
  play: () => void;
  pause: () => void;
  toggle: () => void;
}

/**
 * Timer-driven playback over a frame list. It advances only when the next frame is ready (no
 * blank frames), stops at the end instead of looping, and prefetches ahead while playing.
 * Play at the end replays the last `REPLAY_FRAMES` frames (at the current stride); reaching an
 * earlier date is the slider's job.
 */
export function usePlayback(options: PlaybackOptions): Playback {
  const { fps } = options;
  const [playing, setPlaying] = useState(false);
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    if (!playing) return undefined;
    const id = window.setInterval(
      () => {
        const { index, length, stride, isReady, setIndex } = latest.current;
        if (length === 0 || index >= length - 1) {
          setPlaying(false);
          return;
        }
        const next = Math.min(length - 1, index + Math.max(1, stride));
        if (!isReady(next)) return;
        latest.current = { ...latest.current, index: next };
        setIndex(next);
        if (next >= length - 1) setPlaying(false);
      },
      1000 / Math.max(0.1, fps),
    );
    return () => window.clearInterval(id);
  }, [playing, fps]);

  const { index, length, stride } = options;
  useEffect(() => {
    if (!playing) return;
    const prefetch = latest.current.prefetch;
    if (!prefetch) return;
    for (let k = 1; k <= PREFETCH_AHEAD; k += 1) {
      const target = index + k * Math.max(1, stride);
      if (target > length - 1) break;
      prefetch(target);
    }
  }, [playing, index, length, stride]);

  const play = useCallback(() => {
    const { index: at, length: total, setIndex } = latest.current;
    if (total === 0) return;
    if (at >= total - 1) {
      const step = Math.max(1, latest.current.stride);
      setIndex(Math.max(0, total - 1 - (REPLAY_FRAMES - 1) * step));
    }
    setPlaying(true);
  }, []);
  const pause = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => {
    if (playing) setPlaying(false);
    else play();
  }, [playing, play]);

  const atEnd = length > 0 && index >= length - 1;
  return { playing, atEnd, play, pause, toggle };
}

/** True when the user prefers reduced motion; playback speed is capped at 1x then. */
export function usePrefersReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)';
  const [reduced, setReduced] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const onChange = () => setReduced(media.matches);
    media.addEventListener?.('change', onChange);
    return () => media.removeEventListener?.('change', onChange);
  }, []);
  return reduced;
}
