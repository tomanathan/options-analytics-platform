import { useMemo } from 'react';
import type { PointerEvent } from 'react';
import { curveLinear } from '@visx/curve';
import { scaleLinear } from '@visx/scale';
import { LinePath } from '@visx/shape';
import type { SessionSummary } from '../api/types';
import { pct, usd } from '../lib/format';

const ROW_HEIGHT = 40;
const PAD = 6;
const GAP = 16;

interface SparklineProps {
  label: string;
  values: readonly (number | null)[];
  index: number;
  width: number;
  format: (value: number | null) => string;
  onSeek: (index: number) => void;
}

function Sparkline({ label, values, index, width, format, onSeek }: SparklineProps) {
  const n = values.length;
  const xScale = useMemo(
    () =>
      scaleLinear({
        domain: [0, Math.max(1, n - 1)],
        range: [PAD, Math.max(PAD + 1, width - PAD)],
      }),
    [n, width],
  );
  const yScale = useMemo(() => {
    const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
    const lo = finite.length ? Math.min(...finite) : 0;
    const hi = finite.length ? Math.max(...finite) : 1;
    return scaleLinear({ domain: [lo, hi === lo ? lo + 1 : hi], range: [ROW_HEIGHT - PAD, PAD] });
  }, [values]);

  const current = values[index] ?? null;

  const seekFrom = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const position = Math.round(xScale.invert(x));
    onSeek(Math.min(n - 1, Math.max(0, position)));
  };

  const markerX = xScale(index);
  const markerY = current === null ? null : yScale(current);

  return (
    <div className="sparkline">
      <div className="sparkline__label">
        <span>{label}</span>
        <strong>{format(current)}</strong>
      </div>
      <svg
        width={width}
        height={ROW_HEIGHT}
        role="img"
        aria-label={`${label} over time. Click or drag to choose a session.`}
        className="sparkline__svg"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture?.(event.pointerId);
          seekFrom(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) seekFrom(event);
        }}
      >
        <LinePath
          data={values.map((value, i) => ({ i, value }))}
          x={(d) => xScale(d.i)}
          y={(d) => yScale(d.value ?? 0)}
          defined={(d) => d.value !== null && Number.isFinite(d.value)}
          curve={curveLinear}
          stroke="var(--ink-2)"
          strokeWidth={1.5}
          fill="none"
        />
        <line
          x1={markerX}
          x2={markerX}
          y1={0}
          y2={ROW_HEIGHT}
          stroke="var(--series-1)"
          strokeWidth={1}
        />
        {markerY !== null && (
          <circle
            cx={markerX}
            cy={markerY}
            r={4}
            fill="var(--series-1)"
            stroke="var(--surface-1)"
            strokeWidth={2}
          />
        )}
      </svg>
    </div>
  );
}

interface SessionSparklinesProps {
  sessions: readonly SessionSummary[];
  index: number;
  width: number;
  onSeek: (index: number) => void;
}

/** Underlying close and ATM IV across every session; click or drag to seek. */
export function SessionSparklines({ sessions, index, width, onSeek }: SessionSparklinesProps) {
  const columns = width >= 520 ? 2 : 1;
  const each = Math.floor((width - GAP * (columns - 1)) / columns);
  const closes = useMemo(() => sessions.map((s) => s.underlying_close), [sessions]);
  const ivs = useMemo(() => sessions.map((s) => s.atm_iv), [sessions]);
  return (
    <div className="sparklines">
      <Sparkline
        label="Close"
        values={closes}
        index={index}
        width={each}
        format={(v) => usd(v)}
        onSeek={onSeek}
      />
      <Sparkline
        label="ATM IV"
        values={ivs}
        index={index}
        width={each}
        format={(v) => pct(v)}
        onSeek={onSeek}
      />
    </div>
  );
}
