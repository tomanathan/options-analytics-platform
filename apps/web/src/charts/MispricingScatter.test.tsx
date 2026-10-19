import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SpreadRow } from '../api/types';
import { SPREAD_ROWS } from '../test/fixtures';
import { logTicks, MispricingScatter } from './MispricingScatter';
import type { Highlight } from './scatterLayer';

const MARGIN_LEFT = 56;
const MARGIN_TOP = 14;

const highlights: Highlight[] = [
  { symbol: 'TSLA', slot: 0 },
  { symbol: 'MSFT', slot: 1 },
];

/** A row with chosen mid and fair credits. */
function row(key: string, credit: number, fair: number, width = 5): SpreadRow {
  const base = SPREAD_ROWS[0] as SpreadRow;
  return {
    ...base,
    spread_key: key,
    underlying: 'SPY',
    credit,
    fair_credit: fair,
    edge: credit - fair,
    edge_pct: (credit - fair) / credit,
    width,
  };
}

function renderChart(overrides: Partial<Parameters<typeof MispricingScatter>[0]> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <MispricingScatter
      rows={SPREAD_ROWS}
      highlights={highlights}
      selectedKey={null}
      onSelect={onSelect}
      width={640}
      height={420}
      {...overrides}
    />,
  );
  return { ...view, onSelect };
}

describe('MispricingScatter', () => {
  it('draws the parity line and three edge guides', () => {
    renderChart();
    const parity = screen.getByTestId('parity-line');
    // Equal log domains on both axes: the parity line rises at 45 degrees.
    const dx = Number(parity.getAttribute('x2')) - Number(parity.getAttribute('x1'));
    const dy = Number(parity.getAttribute('y1')) - Number(parity.getAttribute('y2'));
    expect(dx).toBeGreaterThan(0);
    expect(dy).toBeGreaterThan(0);
    const guides = screen.getAllByTestId('edge-guide');
    expect(guides.map((g) => g.getAttribute('data-edge'))).toEqual(['0.25', '0.5', '0.75']);
    expect(screen.getByText('edge 25%')).toBeInTheDocument();
    expect(screen.getByText('edge 75%')).toBeInTheDocument();
  });

  it('marks each point as above or below the parity line', () => {
    const rows = [row('a', 1.0, 0.7), row('b', 0.5, 0.8)];
    const { container } = renderChart({ rows, highlights: [] });
    expect(container.querySelector('[data-key="a"]')?.getAttribute('data-side')).toBe('above');
    expect(container.querySelector('[data-key="b"]')?.getAttribute('data-side')).toBe('below');
  });

  it('puts a point with a higher mid credit above the one with a lower credit, and left of a larger fair credit', () => {
    const rows = [row('a', 1.0, 0.5), row('b', 2.0, 1.0)];
    const { container } = renderChart({ rows, highlights: [] });
    const at = (key: string) => {
      const el = container.querySelector(`circle[data-key="${key}"]`);
      return { cx: Number(el?.getAttribute('cx')), cy: Number(el?.getAttribute('cy')) };
    };
    expect(at('b').cy).toBeLessThan(at('a').cy);
    expect(at('b').cx).toBeGreaterThan(at('a').cx);
  });

  it('grows the point with the spread width', () => {
    const rows = [1, 3, 5, 10].map((w) => row(`w${w}`, 1 + w / 10, 0.8, w));
    const { container } = renderChart({ rows, highlights: [] });
    const radius = (key: string) =>
      Number(container.querySelector(`[data-key="${key}"]`)?.getAttribute('data-r'));
    expect(radius('w3')).toBeGreaterThan(radius('w1'));
    expect(radius('w5')).toBeGreaterThan(radius('w3'));
  });

  it('pins a fair credit below the floor and says so', () => {
    const rows = [row('zero', 0.4, 0), row('ok', 1, 0.8)];
    const { container } = renderChart({ rows, highlights: [] });
    expect(container.querySelectorAll('[data-testid="pt-pinned"]')).toHaveLength(1);
    expect(container.querySelector('[data-testid="pt-pinned"]')?.getAttribute('data-key')).toBe(
      'zero',
    );
    expect(screen.getByTestId('pinned-note')).toHaveTextContent(
      '1 points below $0.01 pinned to the axis floor',
    );
  });

  it('shows no pinned note when every credit is above the floor', () => {
    renderChart();
    expect(screen.queryByTestId('pinned-note')).toBeNull();
  });

  it('colours highlights by slot and lists them in the legend with the guides', () => {
    const { container } = renderChart();
    expect(container.querySelectorAll('[data-slot="1"]').length).toBeGreaterThan(0);
    expect(container.querySelectorAll('[data-slot="3"]')).toHaveLength(0);
    expect(screen.getByText('TSLA')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getByText('Market = fair')).toBeInTheDocument();
    expect(screen.getByText('Edge 25 / 50 / 75%')).toBeInTheDocument();
  });

  it('states the region in neutral words', () => {
    const { container } = renderChart();
    expect(
      screen.getByText('Above the line: market credit exceeds the calibrated fair credit.'),
    ).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\b(buy|sell|recommend|overpriced)\b/i);
  });

  it('has an accessible name', () => {
    renderChart();
    expect(
      screen.getByRole('group', { name: /market mid credit against calibrated fair credit/i }),
    ).toBeInTheDocument();
  });

  it('selects the nearest point on click', () => {
    const { container, onSelect } = renderChart();
    const target = container.querySelector('circle[data-slot="other"]');
    expect(target).not.toBeNull();
    const x = Number(target?.getAttribute('cx')) + MARGIN_LEFT;
    const y = Number(target?.getAttribute('cy')) + MARGIN_TOP;
    fireEvent.click(screen.getByTestId('scatter-hit'), { clientX: x + 1, clientY: y + 1 });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0].spread_key).toBe(target?.getAttribute('data-key'));
  });

  it('rings the selected point', () => {
    renderChart({ selectedKey: SPREAD_ROWS[0]?.spread_key ?? null });
    expect(screen.getByTestId('selected-ring')).toBeInTheDocument();
  });
});

describe('logTicks', () => {
  it('gives 1-2-5 ticks inside the domain', () => {
    expect(logTicks(0.1, 10)).toEqual([0.1, 0.2, 0.5, 1, 2, 5, 10]);
    expect(logTicks(0.03, 0.4)).toEqual([0.05, 0.1, 0.2]);
  });
});
