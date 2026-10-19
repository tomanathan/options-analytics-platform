import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { makeHeatmap } from '../test/fixtures';
import { heatmapHeight, ProbabilityHeatmap } from './ProbabilityHeatmap';

const data = makeHeatmap();

function renderHeatmap(variant: 'raw' | 'calibrated' = 'calibrated') {
  return render(
    <ProbabilityHeatmap
      data={data}
      variant={variant}
      width={900}
      height={heatmapHeight(data.rows.length)}
    />,
  );
}

describe('ProbabilityHeatmap', () => {
  it('draws one cell per expiration and moneyness column', () => {
    const { container } = renderHeatmap();
    expect(container.querySelectorAll('rect.heatmap-cell')).toHaveLength(
      data.rows.length * data.moneyness.length,
    );
    expect(data.moneyness).toHaveLength(41);
  });

  it('hatches exactly the null cells', () => {
    const { container } = renderHeatmap();
    const nulls = data.rows.reduce(
      (count, row) => count + row.prob_below_calibrated.filter((v) => v === null).length,
      0,
    );
    expect(nulls).toBeGreaterThan(0);
    const hatched = container.querySelectorAll('rect.heatmap-cell.hatch');
    expect(hatched).toHaveLength(nulls);
    hatched.forEach((cell) => expect(cell.getAttribute('fill')).toMatch(/^url\(#/));
  });

  it('labels each cell with its probability, strike, moneyness and expiry', () => {
    renderHeatmap();
    const label = screen.getAllByRole('img', { name: /^P\(S<K\) / })[0];
    expect(label?.getAttribute('aria-label')).toMatch(
      /^P\(S<K\) \d+\.\d% · K \$\d+(\.\d+)? · m \d\.\d{2} · Oct 9$/,
    );
  });

  it('explains a null cell instead of extrapolating', () => {
    const { container } = renderHeatmap();
    const cell = container.querySelector('rect.hatch');
    expect(cell?.getAttribute('aria-label')).toContain('outside quoted strikes, not extrapolated');
  });

  it('follows the variant: raw and calibrated values differ', () => {
    const calibrated = renderHeatmap('calibrated').container.querySelector(
      'rect.heatmap-cell:not(.hatch)',
    );
    const raw = renderHeatmap('raw').container.querySelector('rect.heatmap-cell:not(.hatch)');
    expect(calibrated?.getAttribute('aria-label')).not.toBe(raw?.getAttribute('aria-label'));
  });

  it('names the whole chart', () => {
    renderHeatmap();
    expect(
      screen.getByRole('group', { name: /Probability heatmap, calibrated/ }),
    ).toBeInTheDocument();
  });
});
