import type { ReactNode } from 'react';
import { ParentSize } from '@visx/responsive';

interface MeasuredProps {
  /** Height in pixels reserved until the width is known, so the card does not collapse and jump. */
  minHeight?: number;
  children: (width: number) => ReactNode;
}

/**
 * Gives its child the pixel width of the container. Charts themselves only take explicit sizes.
 * Until the first measurement it renders an empty placeholder of `minHeight` pixels.
 */
export function Measured({ minHeight = 0, children }: MeasuredProps) {
  return (
    <ParentSize debounceTime={50} style={{ height: 'auto' }}>
      {({ width }) =>
        width > 0 ? (
          children(Math.floor(width))
        ) : (
          <div
            data-testid="measured-placeholder"
            aria-hidden="true"
            style={{ height: minHeight }}
          />
        )
      }
    </ParentSize>
  );
}
