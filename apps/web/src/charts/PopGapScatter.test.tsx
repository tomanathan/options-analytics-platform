import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { SpreadRow } from '../api/types';
import { SPREAD_ROWS } from '../test/fixtures';
import { PopGapScatter } from './PopGapScatter';
import type { Highlight } from './scatterLayer';

const MARGIN_LEFT = 52;
const MARGIN_TOP = 14;

const highlights: Highlight[] = [{ symbol: 'TSLA', slot: 0 }];

function row(key: string, pop: number, implied: number, width = 5): SpreadRow {
  const base = SPREAD_ROWS[0] as SpreadRow;
  return {
    ...base,
    spread_key: key,
    underlying: 'SPY',
    prob_profit: pop,
    pop_implied: implied,
    pop_gap: pop - implied,
    pop_gap_raw: pop - implied - 0.08,
    width,
  };
}

function renderChart(overrides: Partial<Parameters<typeof PopGapScatter>[0]> = {}) {
  const onSelect = vi.fn();
  const view = render(
    <PopGapScatter
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

describe('PopGapScatter', () => {
  it('draws the 45 degree parity line and the +5 and +10 point guides', () => {
    renderChart();
    const parity = screen.getByTestId('parity-line');
    // 0..100% on both axes with a plot that is wider than tall: the line runs corner to corner.
    expect(Number(parity.getAttribute('x1'))).toBe(0);
    expect(Number(parity.getAttribute('y2'))).toBe(0);
    expect(Number(parity.getAttribute('x2'))).toBeGreaterThan(0);
    expect(Number(parity.getAttribute('y1'))).toBeGreaterThan(0);
    const guides = screen.getAllByTestId('gap-guide');
    expect(guides.map((g) => g.getAttribute('data-gap'))).toEqual(['5', '10']);
    expect(screen.getByText('+5 pts')).toBeInTheDocument();
    expect(screen.getByText('+10 pts')).toBeInTheDocument();
  });

  it('marks points above the line where calibrated POP exceeds the implied POP', () => {
    const rows = [row('up', 0.8, 0.7), row('down', 0.6, 0.7)];
    const { container } = renderChart({ rows, highlights: [] });
    expect(container.querySelector('[data-key="up"]')?.getAttribute('data-side')).toBe('above');
    expect(container.querySelector('[data-key="down"]')?.getAttribute('data-side')).toBe('below');
    // Higher calibrated POP is higher on the page.
    const cy = (key: string) =>
      Number(container.querySelector(`[data-key="${key}"]`)?.getAttribute('cy'));
    expect(cy('up')).toBeLessThan(cy('down'));
  });

  it('grows the point with the spread width', () => {
    const rows = [1, 3, 5, 10].map((w) => row(`w${w}`, 0.7, 0.5, w));
    const { container } = renderChart({ rows, highlights: [] });
    const radius = (key: string) =>
      Number(container.querySelector(`[data-key="${key}"]`)?.getAttribute('data-r'));
    expect(radius('w3')).toBeGreaterThan(radius('w1'));
    expect(radius('w5')).toBeGreaterThan(radius('w3'));
  });

  it('colours highlights and lists the line keys in the legend', () => {
    const { container } = renderChart();
    expect(container.querySelectorAll('[data-slot="1"]').length).toBeGreaterThan(0);
    expect(screen.getByText('Calibrated = implied')).toBeInTheDocument();
    expect(screen.getByText('+5 / +10 points')).toBeInTheDocument();
  });

  it('states the region without trade wording', () => {
    const { container } = renderChart();
    expect(
      screen.getByText(
        /Above the line: the calibrated probability of profit exceeds the probability the credit implies \(ROI = odds; price-implied POP = max loss ÷ width\)\./,
      ),
    ).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\b(buy|sell|recommend)\b/i);
  });

  it('has an accessible name', () => {
    renderChart();
    expect(
      screen.getByRole('group', {
        name: /calibrated probability of profit against the probability/i,
      }),
    ).toBeInTheDocument();
  });

  it('selects the nearest point on click and rings the selection', () => {
    const rows = [row('only', 0.7, 0.5)];
    const { container, onSelect, rerender } = renderChart({ rows, highlights: [] });
    const target = container.querySelector('circle[data-key="only"]');
    const x = Number(target?.getAttribute('cx')) + MARGIN_LEFT;
    const y = Number(target?.getAttribute('cy')) + MARGIN_TOP;
    fireEvent.click(screen.getByTestId('scatter-hit'), { clientX: x + 1, clientY: y + 1 });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0].spread_key).toBe('only');
    rerender(
      <PopGapScatter
        rows={rows}
        highlights={[]}
        selectedKey="only"
        onSelect={onSelect}
        width={640}
        height={420}
      />,
    );
    expect(screen.getByTestId('selected-ring')).toBeInTheDocument();
  });

  it('shows the gap and the raw gap in the tooltip', () => {
    const rows = [row('only', 0.712, 0.625)];
    const { container } = renderChart({ rows, highlights: [] });
    const target = container.querySelector('circle[data-key="only"]');
    const x = Number(target?.getAttribute('cx')) + MARGIN_LEFT;
    const y = Number(target?.getAttribute('cy')) + MARGIN_TOP;
    fireEvent.pointerMove(screen.getByTestId('scatter-hit'), { clientX: x, clientY: y });
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'POP cal 71.2% · price-implied 62.5% · gap +8.7 pts · raw gap +0.7 pts',
    );
  });
});
