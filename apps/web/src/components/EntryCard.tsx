import type { KeyboardEvent } from 'react';
import { busyError, terminalError, useEntrySpreads } from '../api/queries';
import type { SpreadRow } from '../api/types';
import { annualisedRoc, expiryLabel, num, pct, ratio, strike } from '../lib/format';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';

/** The card always asks for this many rows, independent of the page filters. */
export const ENTRY_COUNT = 10;

interface EntryCardProps {
  selectedKey: string | null;
  onSelect: (row: SpreadRow) => void;
}

const HEADERS: { label: string; num: boolean }[] = [
  { label: '#', num: true },
  { label: 'Underlying', num: false },
  { label: 'Exp (DTE)', num: false },
  { label: 'Short/Long', num: true },
  { label: 'Natural', num: true },
  { label: 'POP cal', num: true },
  { label: 'E[R/max loss]', num: true },
  { label: 'Ann. R/max loss', num: true },
  { label: 'Edge %', num: true },
  { label: 'Reward/risk', num: true },
  { label: 'Entry score', num: true },
];

/**
 * The ten best spreads under the API's entry rule, printed as the API states it, with the
 * evidence for the rule under it. The request is fixed (`sort=entry`, eligible only, ten rows),
 * so the page filters never change this list. "Entry score" is the number the rule ranks by
 * (`score_entry`, an annualised return on max loss at the natural credit).
 */
export function EntryCard({ selectedKey, onSelect }: EntryCardProps) {
  const entry = useEntrySpreads();
  const data = entry.data;
  const busy = busyError(entry);
  const failure = terminalError(entry);

  const onKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: SpreadRow) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect(row);
    }
  };

  return (
    <section className="card block entry" aria-label="Top 10 to enter">
      <div className="block__head">
        <h2>Top {ENTRY_COUNT} to enter</h2>
      </div>
      {data && (
        <p className="entry__rule" data-testid="entry-rule">
          {data.entry_rule}
        </p>
      )}
      {data && (
        <p className="entry__evidence" data-testid="entry-evidence">
          {data.entry_evidence}
        </p>
      )}
      <p className="entry__caveat">A ranking of historical calibration, not trade advice.</p>
      {busy && <ErrorState error={busy} variant="banner" />}
      {failure && !busy && <ErrorState error={failure} />}
      {!data && !failure && !busy && <EmptyState title="Loading the entry list…" />}
      {data && data.rows.length === 0 && (
        <EmptyState
          title="No spread passes the entry rule"
          hint="Nothing in the latest session is eligible under the rule above."
        />
      )}
      {data && data.rows.length > 0 && (
        <div className="table-scroll">
          <table className="table table--entry">
            <caption className="visually-hidden">Top 10 spreads to enter</caption>
            <thead>
              <tr>
                {HEADERS.map((header) => (
                  <th key={header.label} scope="col" className={header.num ? 'is-num' : undefined}>
                    {header.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, index) => {
                const selected = row.spread_key === selectedKey;
                return (
                  <tr
                    key={row.spread_key}
                    className={selected ? 'is-selected' : undefined}
                    aria-selected={selected}
                    tabIndex={0}
                    onClick={() => onSelect(row)}
                    onKeyDown={(event) => onKeyDown(event, row)}
                  >
                    <td className="is-num">{row.rank_entry ?? index + 1}</td>
                    <td>{row.underlying}</td>
                    <td>{expiryLabel(row.expiration, row.dte_days)}</td>
                    <td className="is-num">{`${strike(row.short_strike)}/${strike(row.long_strike)}`}</td>
                    <td className="is-num">{num(row.credit_natural)}</td>
                    <td className="is-num">{pct(row.prob_profit)}</td>
                    <td className="is-num">{pct(row.expected_roc, 2)}</td>
                    <td className="is-num">{annualisedRoc(row.annualised_roc)}</td>
                    <td className="is-num">{pct(row.edge_pct)}</td>
                    <td className="is-num">{ratio(row.reward_to_risk)}</td>
                    <td className="is-num">{annualisedRoc(row.score_entry)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
