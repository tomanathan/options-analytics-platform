import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { makeStructures } from '../test/structureFixtures';
import { KINDS } from '../lib/structures';
import { ADVICE_WORDS } from '../test/wording';
import { listJoin, VerdictCard } from './VerdictCard';

describe('VerdictCard', () => {
  it('names the best kind, its legs and return, and compares the spread with the single', () => {
    const data = makeStructures();
    const { container } = render(
      <VerdictCard verdict={data.verdict} kinds={data.kinds} minPop={0.5} />,
    );
    expect(screen.getByTestId('verdict-headline')).toHaveTextContent(
      'For this outcome, the bull call spread serves best',
    );
    expect(screen.getByText('+1 C 515 / -1 C 530')).toBeInTheDocument();
    const comparison = screen.getByTestId('verdict-comparison');
    expect(comparison).toHaveTextContent('Bull call spread 1.74× against long call 1.21× if right');
    expect(comparison).toHaveTextContent('+0.53× for the spread');
    expect(screen.getByText(/never collected/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(ADVICE_WORDS);
  });

  it('says which singles did not qualify when the single side is missing', () => {
    const data = makeStructures();
    const kinds = data.kinds.filter((kind) => KINDS[kind.kind].family === 'spread');
    const { container } = render(
      <VerdictCard
        verdict={{
          ...data.verdict,
          single_kind: null,
          single_return_if_right: null,
          advantage: null,
        }}
        kinds={kinds}
        minPop={0.6}
      />,
    );
    expect(screen.getByTestId('verdict-missing')).toHaveTextContent(
      'No single qualifies: the long call, long put, long straddle and long strangle stay below P(profit | view) ≥ 60%.',
    );
    expect(screen.queryByTestId('verdict-comparison')).toBeNull();
    expect(container.textContent).not.toMatch(ADVICE_WORDS);
  });

  it('says which spreads did not qualify when the spread side is missing', () => {
    const data = makeStructures();
    render(
      <VerdictCard
        verdict={{
          ...data.verdict,
          best_kind: 'long_call',
          spread_kind: null,
          spread_return_if_right: null,
          advantage: null,
        }}
        kinds={data.kinds.filter((kind) => kind.kind === 'long_call')}
        minPop={0.5}
      />,
    );
    expect(screen.getByTestId('verdict-missing')).toHaveTextContent(
      'No spread qualifies: the bull call spread, bear put spread, bull put spread, bear call spread and iron condor stay below P(profit | view) ≥ 50%.',
    );
  });

  it('states plainly when nothing qualifies', () => {
    const data = makeStructures();
    const { container } = render(
      <VerdictCard
        verdict={{ ...data.verdict, best_kind: null, spread_kind: null, single_kind: null }}
        kinds={[]}
        minPop={0.9}
      />,
    );
    expect(screen.getByRole('heading')).toHaveTextContent(
      'No structure qualifies for this outcome',
    );
    expect(container.textContent).toMatch(/P\(profit \| view\) ≥ 90%/);
    expect(container.textContent).not.toMatch(ADVICE_WORDS);
  });

  it('joins lists in prose', () => {
    expect(listJoin(['a'])).toBe('a');
    expect(listJoin(['a', 'b'])).toBe('a and b');
    expect(listJoin(['a', 'b', 'c'])).toBe('a, b and c');
  });
});
