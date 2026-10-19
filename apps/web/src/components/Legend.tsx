import type { MarkerShape } from '../lib/colors';

export interface LegendItem {
  label: string;
  color: string;
  /** Mark kind: a short line, a dashed line, or a point shape. Defaults to a line. */
  mark?: 'line' | 'dash' | MarkerShape;
  muted?: boolean;
}

function Swatch({ item }: { item: LegendItem }) {
  const mark = item.mark ?? 'line';
  const opacity = item.muted ? 0.5 : 1;
  if (mark === 'line' || mark === 'dash') {
    return (
      <svg width="20" height="10" aria-hidden="true">
        <line
          x1="1"
          x2="19"
          y1="5"
          y2="5"
          stroke={item.color}
          strokeWidth="2"
          strokeDasharray={mark === 'dash' ? '4 3' : undefined}
          opacity={opacity}
        />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" aria-hidden="true">
      {mark === 'circle' && <circle cx="6" cy="6" r="4.5" fill={item.color} opacity={opacity} />}
      {mark === 'square' && (
        <rect x="1.5" y="1.5" width="9" height="9" fill={item.color} opacity={opacity} />
      )}
      {mark === 'triangle' && (
        <path d="M6 1 L11 10.5 L1 10.5 Z" fill={item.color} opacity={opacity} />
      )}
    </svg>
  );
}

/** A row of mark keys. Text stays in ink tokens; the mark beside it carries identity. */
export function Legend({ items }: { items: readonly LegendItem[] }) {
  return (
    <ul className="legend">
      {items.map((item) => (
        <li key={item.label} className="legend__item">
          <Swatch item={item} />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  );
}
