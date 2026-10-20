import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  advantageColor,
  DIV_HEX,
  KIND_HEX,
  KIND_ORDER,
  KINDS,
  parseLegs,
  viewBounds,
  viewSentence,
} from './structures';

const tokens = readFileSync(join(process.cwd(), 'src/theme/tokens.css'), 'utf8');
const tokenValue = (name: string) =>
  new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(tokens)?.[1]?.toLowerCase();

describe('kind tokens', () => {
  it('defines a --kind-* token for every kind, equal to the literal mirror', () => {
    KIND_ORDER.forEach((kind) => {
      const name = `kind-${kind.replace(/_/g, '-')}`;
      expect(tokenValue(name)).toBe(KIND_HEX[kind]);
      expect(KINDS[kind].color).toBe(`var(--${name})`);
    });
  });

  it('keeps the diverging poles in step with --div-*', () => {
    expect(tokenValue('div-cool')).toBe(DIV_HEX.cool);
    expect(tokenValue('div-mid')).toBe(DIV_HEX.mid);
    expect(tokenValue('div-warm')).toBe(DIV_HEX.warm);
  });

  it('gives nine distinct colours and dashes exactly the credit structures', () => {
    expect(new Set(Object.values(KIND_HEX)).size).toBe(9);
    const credit = KIND_ORDER.filter((kind) => KINDS[kind].credit);
    expect(credit).toEqual(['bull_put_spread', 'bear_call_spread', 'iron_condor']);
  });
});

describe('parseLegs', () => {
  it('reads signed quantities, rights and strikes', () => {
    expect(parseLegs('-1 P 250 / +1 P 245')).toEqual([
      { quantity: -1, right: 'P', strike: 250 },
      { quantity: 1, right: 'P', strike: 245 },
    ]);
    expect(parseLegs('+1 C 512.5')).toEqual([{ quantity: 1, right: 'C', strike: 512.5 }]);
    expect(parseLegs('nonsense')).toEqual([]);
  });
});

describe('view sentences', () => {
  it('states two-sided, open and outside views in dollars', () => {
    expect(viewBounds(186.5, 201, false)).toBe('Above $186.50 and below $201.00');
    expect(viewBounds(186.5, null, false)).toBe('Above $186.50');
    expect(viewBounds(null, 170, false)).toBe('Below $170.00');
    expect(viewBounds(160, 200, true)).toBe('Below $160.00 or above $200.00');
  });

  it('adds both probabilities', () => {
    expect(
      viewSentence({
        preset: 'up_moderate',
        lo: 186.5,
        hi: 201,
        outside: false,
        lo_moneyness: 1.029,
        hi_moneyness: 1.109,
        prob: 0.3,
        prob_market: 0.27,
      }),
    ).toBe('Above $186.50 and below $201.00: 30.0% calibrated, 27.0% market-implied.');
  });
});

describe('advantageColor', () => {
  it('is grey at zero and for a missing side, and saturates at the poles', () => {
    expect(advantageColor(null)).toBe(DIV_HEX.mid);
    expect(advantageColor(0)).toBe(advantageColor(-0));
    expect(advantageColor(5)).toBe(advantageColor(1));
    expect(advantageColor(-5)).toBe(advantageColor(-1));
    expect(advantageColor(0.5)).not.toBe(advantageColor(-0.5));
  });
});
