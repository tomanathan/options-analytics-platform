import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { assignSlots, ordColor, SEQ_STOPS, seqColor } from './colors';

describe('tokens', () => {
  it('keeps the heatmap ramp in step with --seq-0..7 in tokens.css', () => {
    // Tests run from apps/web (npm test).
    const tokens = readFileSync(join(process.cwd(), 'src/theme/tokens.css'), 'utf8');
    const fromCss = Array.from({ length: 8 }, (_, i) => {
      const match = new RegExp(`--seq-${i}:\\s*(#[0-9a-fA-F]{6})`).exec(tokens);
      return match?.[1]?.toLowerCase();
    });
    expect(fromCss).toEqual([...SEQ_STOPS]);
  });
});

describe('seqColor', () => {
  it('maps 0 and 1 to the ramp ends and clamps outside [0, 1]', () => {
    expect(seqColor(0)).toBe(seqColor(-3));
    expect(seqColor(1)).toBe(seqColor(7));
    expect(seqColor(0)).not.toBe(seqColor(1));
  });

  it('returns a colour string for an interior value', () => {
    expect(seqColor(0.5)).toMatch(/^rgb\(/);
  });
});

describe('ordColor', () => {
  it('numbers expiries from the nearest and clamps to four steps', () => {
    expect(ordColor(0)).toBe('var(--ord-1)');
    expect(ordColor(3)).toBe('var(--ord-4)');
    expect(ordColor(9)).toBe('var(--ord-4)');
    expect(ordColor(-1)).toBe('var(--ord-1)');
  });
});

describe('assignSlots', () => {
  it('assigns slots in the order highlights are added', () => {
    expect(assignSlots({}, ['TSLA', 'MSFT'])).toEqual({ TSLA: 0, MSFT: 1 });
  });

  it('keeps a slot while its underlying stays highlighted', () => {
    const first = assignSlots({}, ['TSLA', 'MSFT', 'SPY']);
    const afterRemoval = assignSlots(first, ['MSFT', 'SPY']);
    expect(afterRemoval).toEqual({ MSFT: 1, SPY: 2 });
    const afterAdd = assignSlots(afterRemoval, ['MSFT', 'SPY', 'XLF']);
    expect(afterAdd).toEqual({ MSFT: 1, SPY: 2, XLF: 0 });
  });

  it('assigns at most three slots', () => {
    expect(Object.keys(assignSlots({}, ['A', 'B', 'C', 'D']))).toHaveLength(3);
  });
});
