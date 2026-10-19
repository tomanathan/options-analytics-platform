import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Highlight } from './SpreadScatter';
import { SpreadScatter } from './SpreadScatter';
import { SPREAD_ROWS } from '../test/fixtures';

const MARGIN_LEFT = 52;
const MARGIN_TOP = 14;

const highlights: Highlight[] = [
  { symbol: 'TSLA', slot: 0 },
  { symbol: 'MSFT', slot: 1 },
];

function renderScatter(overrides: Partial<Parameters<typeof SpreadScatter>[0]> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <SpreadScatter
      rows={SPREAD_ROWS}
      highlights={highlights}
      selectedKey={null}
      onSelect={onSelect}
      minProbProfit={0.5}
      width={640}
      height={380}
      {...overrides}
    />,
  );
  return { ...view, onSelect };
}

describe('SpreadScatter', () => {
  it('colours highlighted underlyings by slot and mutes the rest', () => {
    const { container } = renderScatter();
    const count = (underlying: string) =>
      SPREAD_ROWS.filter((r) => r.underlying === underlying).length;
    expect(container.querySelectorAll('[data-slot="1"]')).toHaveLength(count('TSLA'));
    expect(container.querySelectorAll('[data-slot="2"]')).toHaveLength(count('MSFT'));
    expect(container.querySelectorAll('[data-slot="3"]')).toHaveLength(0);
    const others = container.querySelectorAll('[data-slot="other"]');
    expect(others).toHaveLength(count('SPY') + count('XLF'));
    // Muted points are drawn as faint circles; a pinned one is a small marker, kept more visible.
    container.querySelectorAll('circle[data-slot="other"]').forEach((el) => {
      expect(el.getAttribute('fill')).toBe('var(--ink-muted)');
      expect(Number(el.getAttribute('fill-opacity'))).toBeLessThan(0.5);
    });
    const tsla = container.querySelector('[data-slot="1"]');
    expect(tsla?.getAttribute('fill')).toBe('var(--series-1)');
    expect(container.querySelector('[data-slot="2"]')?.getAttribute('fill')).toBe(
      'var(--series-2)',
    );
  });

  it('uses a different shape per slot', () => {
    const { container } = renderScatter({
      highlights: [...highlights, { symbol: 'SPY', slot: 2 }],
    });
    expect(container.querySelector('[data-slot="1"]')?.tagName.toLowerCase()).toBe('path');
    const paths = ['1', '2', '3'].map(
      (slot) => container.querySelector(`path[data-slot="${slot}"]`)?.getAttribute('d') ?? '',
    );
    expect(paths[0]).toContain('a'); // circle is drawn with arcs
    expect(paths[1]).not.toContain('a');
    expect(paths[1]).not.toBe(paths[2]);
  });

  it('pins points beyond +-100% to the edge and counts them', () => {
    const { container } = renderScatter();
    // The fixture has one row at +250% and one at -180%.
    expect(container.querySelectorAll('[data-testid="pt-pinned"]')).toHaveLength(2);
    expect(screen.getByTestId('pinned-note')).toHaveTextContent('2 points beyond ±100% pinned');
  });

  it('shows no pinned note when every point is in range', () => {
    renderScatter({ rows: SPREAD_ROWS.filter((r) => r.eligible) });
    expect(screen.queryByTestId('pinned-note')).toBeNull();
  });

  it('labels the eligibility line and lists the highlights and Other in the legend', () => {
    renderScatter();
    expect(screen.getByText('eligibility POP ≥ 50%')).toBeInTheDocument();
    expect(screen.getByText('TSLA')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
  });

  it('selects the nearest point on click', () => {
    const { container, onSelect } = renderScatter();
    const target = container.querySelector('circle[data-slot="other"]');
    expect(target).not.toBeNull();
    const x = Number(target?.getAttribute('cx')) + MARGIN_LEFT;
    const y = Number(target?.getAttribute('cy')) + MARGIN_TOP;
    fireEvent.click(screen.getByTestId('scatter-hit'), { clientX: x + 2, clientY: y + 2 });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0].spread_key).toBe(target?.getAttribute('data-key'));
  });

  it('ignores a click far from every point', () => {
    const { onSelect } = renderScatter({ rows: SPREAD_ROWS.slice(0, 1) });
    fireEvent.click(screen.getByTestId('scatter-hit'), {
      clientX: MARGIN_LEFT + 5,
      clientY: MARGIN_TOP + 300,
    });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('rings the selected point', () => {
    renderScatter({ selectedKey: SPREAD_ROWS[0]?.spread_key ?? null });
    expect(screen.getByTestId('selected-ring')).toBeInTheDocument();
  });
});
