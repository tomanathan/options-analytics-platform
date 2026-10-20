import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { makeStructures } from '../test/structureFixtures';
import { quantile, StructurePayoffChart, viewBands, Y_CAP, yTop } from './StructurePayoffChart';
import type { ViewBounds } from './StructurePayoffChart';

const data = makeStructures();

function renderChart(overrides: Partial<Parameters<typeof StructurePayoffChart>[0]> = {}) {
  return render(
    <StructurePayoffChart
      grid={data.grid}
      density={data.density}
      kinds={data.kinds}
      selected="bull_call_spread"
      view={data.view}
      close={data.underlying_close}
      dominance={data.dominance}
      width={800}
      height={420}
      {...overrides}
    />,
  );
}

describe('StructurePayoffChart', () => {
  it('draws one line per kind and puts the selected one on top, thick and opaque', () => {
    const { container } = renderChart();
    const lines = container.querySelectorAll('[data-testid^="kind-line-"]');
    expect(lines).toHaveLength(data.kinds.length);
    const selected = screen.getByTestId('kind-line-bull_call_spread');
    expect(selected).toHaveAttribute('data-selected', 'true');
    expect(selected.getAttribute('stroke-width')).toBe('3');
    expect(selected.getAttribute('stroke')).toBe('var(--kind-bull-call-spread)');
    expect(lines[lines.length - 1]).toBe(selected);
    const other = screen.getByTestId('kind-line-long_call');
    expect(Number(other.getAttribute('stroke-opacity'))).toBeCloseTo(0.6);
    // Credit structures are dashed, debit ones solid.
    expect(screen.getByTestId('kind-line-bull_put_spread').getAttribute('stroke-dasharray')).toBe(
      '6 4',
    );
    expect(other.getAttribute('stroke-dasharray')).toBeNull();
  });

  it('shades the view once inside and twice for an outside view', () => {
    renderChart();
    expect(screen.getAllByTestId('view-shade')).toHaveLength(1);
    const outside = makeStructures({ preset: 'big_move' });
    renderChart({ view: outside.view });
    expect(screen.getAllByTestId('view-shade')).toHaveLength(1 + 2);
  });

  it('marks the zero line, the close, the density and the selected kind’s breakevens', () => {
    renderChart({ selected: 'long_straddle' });
    expect(screen.getByTestId('zero-line')).toBeInTheDocument();
    expect(screen.getByTestId('density')).toBeInTheDocument();
    expect(within(screen.getByTestId('close-marker')).getByText('close $512.34')).toBeTruthy();
    expect(screen.getAllByTestId('breakeven')).toHaveLength(2);
  });

  it('colours the dominance strip by the winning kind and lists them in a legend', () => {
    renderChart();
    const segments = screen.getAllByTestId('dominance-segment');
    expect(segments).toHaveLength(data.dominance.length);
    segments.forEach((segment, i) => {
      const kind = data.dominance[i]?.kind ?? '';
      expect(segment).toHaveAttribute('data-kind', kind);
      expect(segment.getAttribute('fill')).toBe(`var(--kind-${kind.replace(/_/g, '-')})`);
    });
    const legend = screen.getByTestId('dominance-legend');
    expect(within(legend).getByText('Long put')).toBeInTheDocument();
    expect(
      within(legend).getByText('Strip: highest return on max loss at each price'),
    ).toBeTruthy();
  });

  it('flags lines that run off the top of the scale', () => {
    renderChart();
    // The long call and the straddle keep rising past the 95th percentile of the others.
    expect(screen.getByTestId('off-scale')).toHaveTextContent(/off scale above/);
  });

  it('lists every kind’s return at the hovered price, highest first', () => {
    const { container } = renderChart();
    const hit = screen.getByTestId('payoff-hit');
    fireEvent.pointerMove(hit, { clientX: 52 + 780, clientY: 100 });
    const tooltip = screen.getByRole('tooltip');
    const values = within(tooltip)
      .getAllByText(/×$/)
      .map((el) => Number(el.textContent?.replace('×', '')));
    expect(values).toHaveLength(data.kinds.length);
    expect([...values].sort((a, b) => b - a)).toEqual(values);
    expect(within(tooltip).getByText('price at expiry')).toBeInTheDocument();
    fireEvent.pointerLeave(hit);
    expect(container.querySelector('[role="tooltip"]')).toBeNull();
  });
});

describe('chart helpers', () => {
  it('takes the nearest-rank quantile and caps the y axis', () => {
    expect(quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95)).toBe(10);
    expect(quantile([3, 1, 2], 0.5)).toBe(2);
    expect(yTop([{ ...data.kinds[0]!, curve: Array.from({ length: 100 }, (_, i) => i) }])).toBe(
      Y_CAP,
    );
    expect(yTop([{ ...data.kinds[0]!, curve: [-1, 0, 0.1] }])).toBe(0.5);
  });

  it('builds one band inside and the two tails outside, clipped to the domain', () => {
    const domain = [100, 200] as const;
    const inside: ViewBounds = { lo: 120, hi: 150, outside: false };
    expect(viewBands(inside, domain)).toEqual([[120, 150]]);
    expect(viewBands({ ...inside, outside: true }, domain)).toEqual([
      [100, 120],
      [150, 200],
    ]);
    expect(viewBands({ lo: 150, hi: null, outside: false }, domain)).toEqual([[150, 200]]);
    expect(viewBands({ lo: null, hi: 130, outside: true }, domain)).toEqual([[130, 200]]);
  });
});
