import type { ReactNode } from 'react';
import { ParentSize } from '@visx/responsive';

interface MeasuredProps {
  children: (width: number) => ReactNode;
}

/** Gives its child the pixel width of the container. Charts themselves only take explicit sizes. */
export function Measured({ children }: MeasuredProps) {
  return (
    <ParentSize debounceTime={50} style={{ height: 'auto' }}>
      {({ width }) => (width > 0 ? children(Math.floor(width)) : null)}
    </ParentSize>
  );
}
