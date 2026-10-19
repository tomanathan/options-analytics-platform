export interface TooltipLine {
  /** The figure, shown first and strongest. */
  value: string;
  /** What the figure is. */
  label?: string;
  /** Series colour for the short line key; omitted for plain rows. */
  color?: string;
  dashed?: boolean;
}

interface ChartTooltipProps {
  /** Pointer position in the chart container's pixel space. */
  left: number;
  top: number;
  containerWidth: number;
  lines: readonly TooltipLine[];
  /** Context row under the values (strike, moneyness, DTE...). */
  footer?: string;
}

/** One tooltip for the whole chart: values lead, labels follow, keyed by short line swatches. */
export function ChartTooltip({ left, top, containerWidth, lines, footer }: ChartTooltipProps) {
  const flip = left > containerWidth / 2;
  return (
    <div
      className="tooltip"
      role="tooltip"
      style={{
        left,
        top,
        transform: flip ? 'translate(calc(-100% - 14px), -50%)' : 'translate(14px, -50%)',
      }}
    >
      {lines.map((line, index) => (
        <div className="tooltip__row" key={`${index}-${line.label ?? line.value}`}>
          {line.color && (
            <svg width="14" height="8" aria-hidden="true">
              <line
                x1="0"
                x2="14"
                y1="4"
                y2="4"
                stroke={line.color}
                strokeWidth="2"
                strokeDasharray={line.dashed ? '3 2' : undefined}
              />
            </svg>
          )}
          <strong className="tooltip__value">{line.value}</strong>
          {line.label && <span className="tooltip__label">{line.label}</span>}
        </div>
      ))}
      {footer && <div className="tooltip__footer">{footer}</div>}
    </div>
  );
}
