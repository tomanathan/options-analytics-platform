import { useRef, useState } from 'react';
import type { FocusEvent, MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import type { Fill, MapChoice, OutcomeCell, OutcomeMapResponse, OutcomeRow } from '../api/types';
import { expiryLabel, multiple, pct, signedMultiple } from '../lib/format';
import {
  ADVANTAGE_SATURATION,
  advantageColor,
  DIRECTION_GLYPH,
  DIV_HEX,
  KINDS,
  PRESETS,
  viewBounds,
} from '../lib/structures';
import { structuresHref } from '../state/useStructureParams';
import { ChartTooltip } from './ChartTooltip';
import type { TooltipLine } from './ChartTooltip';

interface OutcomeMatrixProps {
  data: OutcomeMapResponse;
  fill: Fill;
  map: MapChoice;
  minPop: number;
  refreshing?: boolean;
}

interface Hover {
  row: OutcomeRow;
  cell: OutcomeCell;
  left: number;
  top: number;
}

const presetOutside = (id: OutcomeCell['preset']) =>
  PRESETS.find((preset) => preset.id === id)?.outside ?? false;

function tooltipLines(cell: OutcomeCell): TooltipLine[] {
  const side = (
    role: 'spread' | 'single',
    kind: OutcomeCell['spread_kind'],
    value: number | null,
  ): TooltipLine =>
    kind === null
      ? { value: 'none qualifies', label: role }
      : {
          value: multiple(value),
          label: `${role}: ${KINDS[kind].label.toLowerCase()}`,
          color: KINDS[kind].color,
          dashed: KINDS[kind].credit,
        };
  return [
    { value: viewBounds(cell.lo, cell.hi, presetOutside(cell.preset)) },
    { value: pct(cell.prob), label: 'calibrated' },
    { value: pct(cell.prob_market), label: 'market-implied' },
    side('spread', cell.spread_kind, cell.spread_return_if_right),
    side('single', cell.single_kind, cell.single_return_if_right),
    { value: signedMultiple(cell.advantage), label: 'for the spread, if right' },
  ];
}

/** Gradient key of the advantage scale. */
function AdvantageLegend() {
  const stops = [-1, -0.5, 0, 0.5, 1].map((t) => t * ADVANTAGE_SATURATION);
  return (
    <div className="matrix-legend" data-testid="advantage-legend">
      <span className="scatter__note">singles return more</span>
      <svg width="160" height="24" aria-hidden="true">
        <defs>
          <linearGradient id="advantage-ramp" x1="0" x2="1" y1="0" y2="0">
            {stops.map((value, i) => (
              <stop
                key={value}
                offset={`${(i / (stops.length - 1)) * 100}%`}
                stopColor={advantageColor(value)}
              />
            ))}
          </linearGradient>
        </defs>
        <rect x="0" y="0" width="160" height="10" rx="2" fill="url(#advantage-ramp)" />
        <text x="0" y="22" fill="var(--ink-muted)" fontSize="10">
          {signedMultiple(-ADVANTAGE_SATURATION, 1)}
        </text>
        <text x="80" y="22" fill="var(--ink-muted)" fontSize="10" textAnchor="middle">
          0
        </text>
        <text x="160" y="22" fill="var(--ink-muted)" fontSize="10" textAnchor="end">
          {signedMultiple(ADVANTAGE_SATURATION, 1)}
        </text>
      </svg>
      <span className="scatter__note">spreads return more (if right)</span>
      <span className="matrix-legend__missing">
        <span className="swatch" style={{ background: DIV_HEX.mid }} aria-hidden="true" />
        one side missing
      </span>
    </div>
  );
}

/**
 * Tickers by preset outcome: the kind that serves each outcome best and how much the best spread
 * returns over the best single if right. Each cell links to the structures page for that state.
 */
export function OutcomeMatrix({ data, fill, map, minPop, refreshing }: OutcomeMatrixProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);
  const rows = [...data.rows].sort((a, b) => a.symbol.localeCompare(b.symbol));
  const presets = data.presets;

  const show = (
    event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>,
    row: OutcomeRow,
    cell: OutcomeCell,
  ) => {
    const box = wrap.current?.getBoundingClientRect();
    const target = event.currentTarget.getBoundingClientRect();
    setHover({
      row,
      cell,
      left: target.left - (box?.left ?? 0) + target.width / 2,
      top: target.top - (box?.top ?? 0) + target.height / 2,
    });
  };

  return (
    <div className={refreshing ? 'matrix is-refreshing' : 'matrix'}>
      <div className="matrix__wrap" ref={wrap} onMouseLeave={() => setHover(null)}>
        <div className="table-scroll">
          <table className="table table--matrix">
            <caption className="visually-hidden">
              Best structure kind by underlying and outcome, coloured by the spread&apos;s advantage
              over the single if right
            </caption>
            <thead>
              <tr>
                <th scope="col">Underlying</th>
                {presets.map((preset) => (
                  <th key={preset.id} scope="col" className="is-center" title={preset.label}>
                    {preset.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol} data-testid={`matrix-row-${row.symbol}`}>
                  <th scope="row">
                    {row.symbol}
                    {row.expiration !== null && row.dte_days !== null && (
                      <span className="table__sub">
                        {expiryLabel(row.expiration, row.dte_days)}
                      </span>
                    )}
                  </th>
                  {row.cells.length === 0 ? (
                    <td colSpan={presets.length} className="matrix__empty">
                      {row.unavailable_reason ?? 'No usable expiration for this session.'}
                    </td>
                  ) : (
                    presets.map((preset) => {
                      const cell = row.cells.find((c) => c.preset === preset.id);
                      if (!cell) {
                        return (
                          <td key={preset.id} className="matrix__empty">
                            not computed
                          </td>
                        );
                      }
                      const kind = cell.best_kind;
                      return (
                        <td
                          key={preset.id}
                          className="matrix__cell"
                          style={{ background: advantageColor(cell.advantage) }}
                          data-advantage={cell.advantage ?? ''}
                        >
                          <Link
                            to={structuresHref({
                              symbol: row.symbol,
                              session: data.session,
                              expiration: row.expiration,
                              preset: preset.id,
                              fill,
                              map,
                              minPop,
                            })}
                            className="matrix__link"
                            aria-label={`${row.symbol}, ${preset.label}: ${
                              kind ? KINDS[kind].label : 'no structure qualifies'
                            }`}
                            onMouseEnter={(event) => show(event, row, cell)}
                            onFocus={(event) => show(event, row, cell)}
                            onBlur={() => setHover(null)}
                          >
                            {kind === null ? (
                              <span className="matrix__none">none qualifies</span>
                            ) : (
                              <>
                                <span className="matrix__kind">
                                  <span aria-hidden="true">
                                    {DIRECTION_GLYPH[KINDS[kind].direction]}
                                  </span>{' '}
                                  {KINDS[kind].short}
                                </span>
                                <span className="matrix__value">
                                  {multiple(cell.best_return_if_right)}
                                </span>
                              </>
                            )}
                          </Link>
                        </td>
                      );
                    })
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hover && (
          <ChartTooltip
            left={hover.left}
            top={hover.top}
            containerWidth={wrap.current?.clientWidth ?? 0}
            lines={tooltipLines(hover.cell)}
            footer={`${hover.row.symbol} · ${
              presets.find((p) => p.id === hover.cell.preset)?.label ?? hover.cell.preset
            }${hover.cell.best_legs ? ` · best ${hover.cell.best_legs}` : ''}`}
          />
        )}
      </div>
      <AdvantageLegend />
    </div>
  );
}
