import { describe, expect, it } from 'vitest';
import { describeFlag, orderFlags } from './flags';

describe('flags', () => {
  it('treats clipped and monotonicity_repaired as info chips', () => {
    for (const flag of ['clipped', 'monotonicity_repaired']) {
      const info = describeFlag(flag);
      expect(info.kind).toBe('info');
      expect(info.icon).toBe('ⓘ');
      expect(info.meaning.length).toBeGreaterThan(10);
    }
  });

  it('treats coverage and data problems as warnings', () => {
    for (const flag of [
      'left_tail_uncovered',
      'right_tail_uncovered',
      'sparse',
      'forward_unknown',
      'no_calls',
    ]) {
      const info = describeFlag(flag);
      expect(info.kind).toBe('warning');
      expect(info.icon).toBe('⚠');
    }
  });

  it('labels flags in words', () => {
    expect(describeFlag('left_tail_uncovered').label).toBe('left tail uncovered');
    expect(describeFlag('monotonicity_repaired').label).toBe('monotonicity repaired');
  });

  it('shows an unknown flag as a warning so nothing is hidden', () => {
    const info = describeFlag('brand_new_flag');
    expect(info.kind).toBe('warning');
    expect(info.label).toBe('brand new flag');
    expect(info.meaning).toContain('brand_new_flag');
  });

  it('orders warnings before info chips, alphabetically within each', () => {
    expect(orderFlags(['clipped', 'sparse', 'left_tail_uncovered']).map((f) => f.flag)).toEqual([
      'left_tail_uncovered',
      'sparse',
      'clipped',
    ]);
  });
});
