import type { ReactNode } from 'react';
import { Group } from '@visx/group';
import type { Margin } from './axes';

interface ChartFrameProps {
  width: number;
  height: number;
  margin: Margin;
  /** Accessible name; charts also expose their data through a table or the tooltip. */
  label: string;
  /** `img` for charts that are one picture; `group` when children carry their own labels. */
  role?: 'img' | 'group';
  children: ReactNode;
  /** Absolutely positioned content (the tooltip) layered over the SVG. */
  overlay?: ReactNode;
  /** The previous render is kept at reduced opacity while a refetch is in flight. */
  refreshing?: boolean;
}

/** An SVG sized by its props, with the plot origin moved inside the margins. */
export function ChartFrame({
  width,
  height,
  margin,
  label,
  role = 'img',
  children,
  overlay,
  refreshing,
}: ChartFrameProps) {
  return (
    <div className={refreshing ? 'chart is-refreshing' : 'chart'} style={{ width, height }}>
      <svg width={width} height={height} role={role} aria-label={label}>
        <Group left={margin.left} top={margin.top}>
          {children}
        </Group>
      </svg>
      {overlay}
    </div>
  );
}
