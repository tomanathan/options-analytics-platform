import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ExpiryDistribution } from '../api/types';
import { makeDistribution } from '../test/fixtures';
import { CdfOverlay, CdfPanel } from './CdfPanel';
import { MONEYNESS_DOMAIN } from './options';
import type { PlotSeries, View } from './options';

const dist = makeDistribution();
const [settled, flagged, plain] = dist.expirations as [
  ExpiryDistribution,
  ExpiryDistribution,
  ExpiryDistribution,
];

function renderPanel(expiry: ExpiryDistribution | null, view: View = 'both') {
  return render(
    <CdfPanel
      expiry={expiry}
      color="var(--ord-1)"
      view={view}
      xMode="moneyness"
      xDomain={MONEYNESS_DOMAIN}
      width={420}
      height={300}
    />,
  );
}

describe('CdfPanel', () => {
  it('draws the calibrated and the raw path in the "both" view', () => {
    renderPanel(settled, 'both');
    const calibrated = screen.getByTestId('cdf-calibrated');
    const raw = screen.getByTestId('cdf-raw');
    expect(calibrated.getAttribute('stroke')).toBe('var(--ord-1)');
    expect(calibrated.getAttribute('stroke-width')).toBe('2');
    expect(raw.getAttribute('stroke')).toBe('var(--raw)');
    expect(raw.getAttribute('stroke-dasharray')).toBeTruthy();
  });

  it('draws one path in the single views', () => {
    const { unmount } = renderPanel(settled, 'calibrated');
    expect(screen.getByTestId('cdf-calibrated')).toBeInTheDocument();
    expect(screen.queryByTestId('cdf-raw')).toBeNull();
    unmount();
    renderPanel(settled, 'raw');
    expect(screen.getByTestId('cdf-raw')).toBeInTheDocument();
    expect(screen.queryByTestId('cdf-calibrated')).toBeNull();
  });

  it('labels the forward and the close', () => {
    const { container } = renderPanel(plain);
    expect(screen.getByText(`F ${plain.forward?.toFixed(2)}`)).toBeInTheDocument();
    expect(Array.from(container.querySelectorAll('text')).some((t) => t.textContent === 'S')).toBe(
      true,
    );
  });

  it('marks the settlement on the curve with its label', () => {
    renderPanel(settled);
    expect(screen.getByTestId('settlement-marker')).toBeInTheDocument();
    expect(screen.getByText('settled $498.20 · P=0.33')).toBeInTheDocument();
  });

  it('shows info and warning chips with a one-line meaning', () => {
    renderPanel(flagged);
    const warning = screen.getByText('left tail uncovered').closest('.chip');
    expect(warning).toHaveClass('chip--warning');
    expect(warning?.getAttribute('title')).toMatch(/low-price tail/);
    expect(screen.getByText('sparse').closest('.chip')).toHaveClass('chip--warning');
    expect(screen.queryByText('clipped')).toBeNull();
  });

  it('shows an info chip for clipped', () => {
    renderPanel(settled);
    expect(screen.getByText('clipped').closest('.chip')).toHaveClass('chip--info');
  });

  it('titles the panel with the expiry and days', () => {
    renderPanel(settled);
    expect(screen.getByRole('heading', { level: 3, name: 'Oct 9 · 7d' })).toBeInTheDocument();
  });

  it('says so for an empty slot', () => {
    renderPanel(null);
    expect(screen.getByText('No expiration in this slot')).toBeInTheDocument();
  });

  it('gives the reason when an expiry has no curve', () => {
    renderPanel({ ...settled, curve: null, unavailable_reason: 'too_few_puts', flags: [] });
    expect(screen.getByText('No curve for this expiration')).toBeInTheDocument();
    expect(screen.getByText('too_few_puts')).toBeInTheDocument();
    expect(screen.queryByTestId('cdf-calibrated')).toBeNull();
  });

  it('shows one tooltip with the value first when the curve is inspected by keyboard', () => {
    const { container } = renderPanel(plain);
    const hit = container.querySelector('rect[tabindex="0"]');
    expect(hit).not.toBeNull();
    fireEvent.keyDown(hit as Element, { key: 'ArrowRight' });
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('P(S<K) calibrated');
    expect(tooltip).toHaveTextContent('P(S<K) raw');
    expect(tooltip).toHaveTextContent('density');
    expect(tooltip).toHaveTextContent(/K \$[\d.]+ · m [\d.]+ · Oct 23 · 21d/);
  });
});

describe('CdfOverlay', () => {
  it('shares one plot and labels each expiry directly', () => {
    const series: PlotSeries[] = dist.expirations.flatMap((expiry, i) =>
      expiry.curve ? [{ expiry, curve: expiry.curve, color: `var(--ord-${i + 1})` }] : [],
    );
    const { container } = render(
      <CdfOverlay
        series={series}
        view="calibrated"
        xMode="moneyness"
        xDomain={MONEYNESS_DOMAIN}
        width={600}
        height={320}
      />,
    );
    expect(screen.getAllByTestId('cdf-calibrated')).toHaveLength(4);
    const labels = Array.from(container.querySelectorAll('text')).map((t) => t.textContent);
    ['7d', '14d', '21d', '49d'].forEach((label) => expect(labels).toContain(label));
  });
});
