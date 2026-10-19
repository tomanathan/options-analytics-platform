import { useMemo } from 'react';
import type { ChainExpiry, ChainQuote } from '../api/types';
import { num, pct, strike } from '../lib/format';

interface Straddle {
  strike: number;
  moneyness: number | null;
  call: ChainQuote | null;
  put: ChainQuote | null;
}

/** Pair calls and puts at each strike, ascending. */
export function toStraddles(expiry: ChainExpiry): Straddle[] {
  const byStrike = new Map<number, Straddle>();
  for (const quote of expiry.quotes) {
    const row = byStrike.get(quote.strike) ?? {
      strike: quote.strike,
      moneyness: null,
      call: null,
      put: null,
    };
    if (quote.option_right === 'C') row.call = quote;
    else row.put = quote;
    row.moneyness = row.moneyness ?? quote.moneyness;
    byStrike.set(quote.strike, row);
  }
  return [...byStrike.values()].sort((a, b) => a.strike - b.strike);
}

function Cells({ quote, side }: { quote: ChainQuote | null; side: 'call' | 'put' }) {
  const muted = quote !== null && !quote.usable;
  const className = muted ? `is-num is-muted side-${side}` : `is-num side-${side}`;
  const title = muted ? 'excluded: zero bid or crossed' : undefined;
  return (
    <>
      <td className={className} title={title}>
        {num(quote?.bid)}
      </td>
      <td className={className} title={title}>
        {num(quote?.ask)}
      </td>
      <td className={className} title={title}>
        {num(quote?.mid)}
      </td>
      <td className={className} title={title}>
        {pct(quote?.iv)}
      </td>
      <td className={className} title={title}>
        {num(quote?.delta)}
      </td>
    </>
  );
}

interface ChainTableProps {
  expiry: ChainExpiry;
  close: number | null;
}

/** Straddle layout: calls on the left, strike in the middle, puts on the right. */
export function ChainTable({ expiry, close }: ChainTableProps) {
  const rows = useMemo(() => toStraddles(expiry), [expiry]);
  const atm = useMemo(() => {
    if (close === null || rows.length === 0) return null;
    return rows.reduce((best, row) =>
      Math.abs(row.strike - close) < Math.abs(best.strike - close) ? row : best,
    ).strike;
  }, [rows, close]);

  return (
    <div className="table-scroll">
      <table className="table table--chain">
        <caption className="visually-hidden">
          Option chain for {expiry.expiration}, {expiry.dte_days} days to expiry
        </caption>
        <thead>
          <tr>
            <th colSpan={5} scope="colgroup" className="is-center">
              Calls
            </th>
            <th rowSpan={2} scope="col" className="is-center">
              Strike
            </th>
            <th colSpan={5} scope="colgroup" className="is-center">
              Puts
            </th>
          </tr>
          <tr>
            {['Bid', 'Ask', 'Mid', 'IV', 'Δ'].map((name) => (
              <th key={`c-${name}`} scope="col" className="is-num">
                {name}
              </th>
            ))}
            {['Bid', 'Ask', 'Mid', 'IV', 'Δ'].map((name) => (
              <th key={`p-${name}`} scope="col" className="is-num">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.strike}
              className={row.strike === atm ? 'is-atm' : undefined}
              aria-current={row.strike === atm ? 'true' : undefined}
            >
              <Cells quote={row.call} side="call" />
              <th scope="row" className="is-center table__strike">
                {strike(row.strike)}
                {row.moneyness !== null && (
                  <span className="table__sub">m {num(row.moneyness, 3)}</span>
                )}
              </th>
              <Cells quote={row.put} side="put" />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
