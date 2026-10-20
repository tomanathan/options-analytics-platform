import type { StructureRow } from '../api/types';
import { annualisedRoc, multiple, pct, ratio, signedPct, usd } from '../lib/format';
import { DIRECTION_GLYPH, KINDS } from '../lib/structures';
import { Chip } from './Chip';
import { DataTable } from './DataTable';
import type { Column } from './DataTable';

/** Above this share of the expected P&L from the completed tails, a row carries a "tail" chip. */
export const TAIL_SHARE_FLAG = 0.25;

/** "$3.10 debit" or "-$1.20 credit": positive net premium is paid, negative received ($/sh). */
export function premiumLabel(netPremium: number): string {
  return `${usd(netPremium)} ${netPremium > 0 ? 'debit' : 'credit'}`;
}

export function KindCell({ row }: { row: StructureRow }) {
  const meta = KINDS[row.kind];
  return (
    <span className="kind-cell">
      <span className="swatch" style={{ background: meta.color }} aria-hidden="true" />
      <span className="kind-cell__glyph" title={`direction: ${row.direction}`}>
        {DIRECTION_GLYPH[row.direction]}
      </span>
      {meta.label}
    </span>
  );
}

/** Columns shared by the kinds table and the "All qualifying structures" table. */
export const STRUCTURE_COLUMNS: readonly Column<StructureRow>[] = [
  {
    key: 'kind',
    header: 'Kind',
    sortValue: (r) => KINDS[r.kind].label,
    cell: (r) => <KindCell row={r} />,
  },
  { key: 'legs', header: 'Legs', cell: (r) => r.legs },
  {
    key: 'premium',
    header: 'Premium',
    align: 'right',
    title: 'Net premium, $/sh: a debit is paid, a credit received',
    sortValue: (r) => r.net_premium,
    cell: (r) => premiumLabel(r.net_premium),
  },
  {
    key: 'max_loss',
    header: 'Max loss',
    align: 'right',
    title: '$/sh; capital at risk',
    sortValue: (r) => r.max_loss,
    cell: (r) => usd(r.max_loss),
  },
  {
    key: 'max_gain',
    header: 'Max gain',
    align: 'right',
    title: '$/sh; ∞ when the payoff is unbounded',
    sortValue: (r) => r.max_gain ?? Number.POSITIVE_INFINITY,
    cell: (r) => (r.max_gain === null ? '∞' : usd(r.max_gain)),
  },
  {
    key: 'breakevens',
    header: 'Breakevens',
    align: 'right',
    cell: (r) => r.breakevens.map((b) => usd(b)).join(' · ') || '–',
  },
  {
    key: 'pop_given',
    header: 'P(profit | view)',
    align: 'right',
    sortValue: (r) => r.prob_profit_given_view,
    cell: (r) => pct(r.prob_profit_given_view),
  },
  {
    key: 'return_if_right',
    header: 'Return if right',
    align: 'right',
    title: 'Expected P&L when the price lands in the view, per dollar of max loss',
    sortValue: (r) => r.return_if_right,
    cell: (r) => <strong>{multiple(r.return_if_right)}</strong>,
  },
  {
    key: 'return_if_wrong',
    header: 'Return if wrong',
    align: 'right',
    title: 'Expected P&L when the price lands outside the view, per dollar of max loss',
    sortValue: (r) => r.return_if_wrong,
    cell: (r) => multiple(r.return_if_wrong),
  },
  {
    key: 'worst_in_view',
    header: 'Worst in view',
    align: 'right',
    title: 'Lowest P&L over max loss for any price in the view',
    sortValue: (r) => r.worst_in_view,
    cell: (r) => multiple(r.worst_in_view),
  },
  {
    key: 'expected_return',
    header: 'E[R/max loss]',
    align: 'right',
    title: 'Unconditional expected return on max loss, holding period',
    sortValue: (r) => r.expected_return,
    cell: (r) => signedPct(r.expected_return, 1),
  },
  {
    key: 'annualised',
    header: 'Ann. R/max loss',
    align: 'right',
    sortValue: (r) => r.annualised_return,
    cell: (r) => annualisedRoc(r.annualised_return),
  },
  {
    key: 'pop',
    header: 'P(profit)',
    align: 'right',
    sortValue: (r) => r.prob_profit,
    cell: (r) => pct(r.prob_profit),
  },
  {
    key: 'reward_to_risk',
    header: 'Reward/risk',
    align: 'right',
    title: 'Expected P&L over its standard deviation, per trade, not annualised',
    sortValue: (r) => r.reward_to_risk,
    cell: (r) => ratio(r.reward_to_risk),
  },
  {
    key: 'tail_share',
    header: 'Tail share',
    align: 'right',
    title: 'Share of the expected P&L that comes from beyond the quoted strikes',
    sortValue: (r) => r.tail_share,
    cell: (r) => (
      <span className="chips chips--end">
        {r.tail_share > TAIL_SHARE_FLAG && (
          <Chip
            kind="warning"
            icon={'⚠'}
            title="More than a quarter of the expected P&L comes from the modelled tails beyond the quoted strikes."
          >
            tail
          </Chip>
        )}
        {pct(r.tail_share, 0)}
      </span>
    ),
  },
];

const DEFAULT_SORT = { key: 'return_if_right', direction: 'descending' } as const;

interface StructureTableProps {
  caption: string;
  rows: readonly StructureRow[];
  rowKey: (row: StructureRow) => string;
  selectedKey?: string | null;
  onSelect?: (row: StructureRow) => void;
  pageSize?: number;
}

/** A structures table sorted by return if right; the kinds table and the ranking share it. */
export function StructureTable({
  caption,
  rows,
  rowKey,
  selectedKey = null,
  onSelect,
  pageSize = 25,
}: StructureTableProps) {
  return (
    <DataTable
      caption={caption}
      columns={STRUCTURE_COLUMNS}
      rows={rows}
      rowKey={rowKey}
      pageSize={pageSize}
      defaultSort={DEFAULT_SORT}
      selectedKey={selectedKey}
      onSelect={onSelect}
    />
  );
}

interface KindsTableProps {
  kinds: readonly StructureRow[];
  selected: StructureRow['kind'] | null;
  onSelect: (row: StructureRow) => void;
}

/** One row per kind (its best structure for the view); a click selects the kind. */
export function KindsTable({ kinds, selected, onSelect }: KindsTableProps) {
  return (
    <StructureTable
      caption="Best structure of each kind"
      rows={kinds}
      rowKey={(row) => row.kind}
      selectedKey={selected}
      onSelect={onSelect}
    />
  );
}
