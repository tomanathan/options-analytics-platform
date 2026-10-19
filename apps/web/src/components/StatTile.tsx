import type { ReactNode } from 'react';

interface StatTileProps {
  label: string;
  value: string;
  /** A secondary figure such as the raw value or the natural credit. */
  sub?: ReactNode;
}

/** A labelled figure. Proportional numerals: these are standalone values, not a column. */
export function StatTile({ label, value, sub }: StatTileProps) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {sub !== undefined && <div className="stat__sub">{sub}</div>}
    </div>
  );
}
