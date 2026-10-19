import type { KeyboardEvent } from 'react';
import { longDate } from '../lib/format';
import type { Stride } from '../lib/sessions';
import { SegmentedToggle } from './SegmentedToggle';

export type Speed = 1 | 2 | 4;

interface ScrubberProps {
  dates: readonly string[];
  /** Index into `dates` of the session on screen. */
  index: number;
  onSeek: (index: number) => void;
  playing: boolean;
  /** True when the last session is on screen: Play then replays recent history, so say so. */
  atEnd?: boolean;
  onToggle: () => void;
  onStep: (delta: -1 | 1) => void;
  speed: Speed;
  onSpeed: (speed: Speed) => void;
  /** Highest speed allowed (1 when the user prefers reduced motion). */
  maxSpeed: Speed;
  stride: Stride;
  onStride: (stride: Stride) => void;
}

const SPEEDS: readonly Speed[] = [1, 2, 4];

/** Playback controls and a range slider over the session list. Keyboard: Space plays, arrows step. */
export function Scrubber({
  dates,
  index,
  onSeek,
  playing,
  atEnd = false,
  onToggle,
  onStep,
  speed,
  onSpeed,
  maxSpeed,
  stride,
  onStride,
}: ScrubberProps) {
  const date = dates[index] ?? '';

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target instanceof HTMLButtonElement || target instanceof HTMLSelectElement) return;
    if (event.key === ' ') {
      event.preventDefault();
      onToggle();
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      onStep(-1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      onStep(1);
    }
  };

  return (
    <div className="scrubber" role="group" aria-label="Session playback" onKeyDown={onKeyDown}>
      <div className="scrubber__transport">
        <div className="scrubber__buttons">
          <button
            type="button"
            className="button button--icon"
            aria-label="Previous session"
            onClick={() => onStep(-1)}
          >
            {'◀'}
          </button>
          <button
            type="button"
            className="button button--primary"
            aria-pressed={playing}
            onClick={onToggle}
          >
            {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
          </button>
          <button
            type="button"
            className="button button--icon"
            aria-label="Next session"
            onClick={() => onStep(1)}
          >
            {'▶'}
          </button>
        </div>
        <div className="scrubber__track">
          <input
            type="range"
            className="scrubber__range"
            aria-label="Session date"
            min={0}
            max={Math.max(0, dates.length - 1)}
            step={1}
            value={index}
            aria-valuetext={date ? longDate(date) : undefined}
            onChange={(event) => onSeek(Number(event.target.value))}
          />
          <output className="scrubber__date">{date}</output>
        </div>
      </div>
      <div className="scrubber__options">
        <SegmentedToggle
          label="Speed"
          value={speed}
          options={SPEEDS.map((value) => ({
            value,
            label: `${value}×`,
            disabled: value > maxSpeed,
          }))}
          onChange={onSpeed}
        />
        <SegmentedToggle
          label="Stride"
          value={stride}
          options={[
            { value: 'every', label: 'Every' },
            { value: 'weekly', label: 'Weekly' },
            { value: 'monthly', label: 'Monthly' },
          ]}
          onChange={onStride}
        />
      </div>
    </div>
  );
}
