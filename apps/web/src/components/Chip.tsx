import type { ReactNode } from 'react';

interface ChipProps {
  kind?: 'neutral' | 'info' | 'warning';
  icon?: string;
  title?: string;
  children: ReactNode;
}

/** A small status chip. Status colour is only ever paired with an icon and a label. */
export function Chip({ kind = 'neutral', icon, title, children }: ChipProps) {
  return (
    <span className={`chip chip--${kind}`} title={title}>
      {icon && (
        <span className="chip__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </span>
  );
}
