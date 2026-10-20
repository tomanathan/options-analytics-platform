import type { StructureKind, StructureRow, StructureVerdict } from '../api/types';
import { multiple, pct, signedMultiple } from '../lib/format';
import { KIND_ORDER, kindNoun, KINDS } from '../lib/structures';

interface VerdictCardProps {
  verdict: StructureVerdict;
  /** Best structure per kind, as the API lists them. */
  kinds: readonly StructureRow[];
  /** The P(profit | view) floor the kinds were held to. */
  minPop: number;
}

/** "a, b and c". */
export function listJoin(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1] ?? ''}`;
}

function Swatch({ kind }: { kind: StructureKind }) {
  return <span className="swatch" style={{ background: KINDS[kind].color }} aria-hidden="true" />;
}

/** Kinds of one family that did not qualify for the view. */
function missingOf(family: 'spread' | 'single', present: ReadonlySet<StructureKind>): string[] {
  return KIND_ORDER.filter((kind) => KINDS[kind].family === family && !present.has(kind)).map(
    kindNoun,
  );
}

/**
 * Which kind serves the outcome best, and how the best spread compares with the best single
 * when the view is right. Descriptive only: the reason sentence comes from the API.
 */
export function VerdictCard({ verdict, kinds, minPop }: VerdictCardProps) {
  const floor = `P(profit | view) ≥ ${pct(minPop, 0)}`;
  const present = new Set(kinds.map((kind) => kind.kind));
  const best = kinds.find((kind) => kind.kind === verdict.best_kind) ?? null;

  if (verdict.best_kind === null || best === null) {
    return (
      <section className="card block verdict" aria-label="Verdict">
        <h2>No structure qualifies for this outcome</h2>
        <p className="verdict__line">
          None of the nine kinds reaches {floor}. A lower floor or a wider view admits more.
        </p>
      </section>
    );
  }

  const { spread_kind: spread, single_kind: single } = verdict;
  const missingSpreads = missingOf('spread', present);
  const missingSingles = missingOf('single', present);

  return (
    <section className="card block verdict" aria-label="Verdict">
      <h2 data-testid="verdict-headline">
        For this outcome, the {kindNoun(verdict.best_kind)} serves best
      </h2>
      <p className="verdict__line">
        <Swatch kind={verdict.best_kind} />
        <span className="verdict__legs">{best.legs}</span>
        {' · '}
        <strong>{multiple(best.return_if_right)}</strong> on max loss if right
      </p>
      {spread !== null && single !== null ? (
        <p className="verdict__line" data-testid="verdict-comparison">
          <Swatch kind={spread} /> {KINDS[spread].label}{' '}
          <strong>{multiple(verdict.spread_return_if_right)}</strong> against{' '}
          <Swatch kind={single} /> {kindNoun(single)}{' '}
          <strong>{multiple(verdict.single_return_if_right)}</strong> if right
          {' · '}
          <strong>{signedMultiple(verdict.advantage)}</strong> for the spread
        </p>
      ) : (
        <p className="verdict__line" data-testid="verdict-missing">
          {spread === null
            ? `No spread qualifies: the ${listJoin(missingSpreads)} stay below ${floor}.`
            : `No single qualifies: the ${listJoin(missingSingles)} stay below ${floor}.`}
        </p>
      )}
      <p className="verdict__reason">{verdict.reason}</p>
    </section>
  );
}
