import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { CALIBRATION } from '../test/fixtures';
import { server } from '../test/server';
import { CalibrationBadge, calibrationText, calibrationTitle } from './CalibrationBadge';

function renderBadge(variant?: 'compact' | 'full') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <CalibrationBadge variant={variant} />
    </QueryClientProvider>,
  );
}

describe('CalibrationBadge', () => {
  it('summarises ECE and Brier from the gold metric names', () => {
    expect(calibrationText(CALIBRATION)).toBe('ECE 3.5%→1.7% · Brier 0.127→0.129');
  });

  it('puts the confidence intervals in the tooltip', () => {
    const title = calibrationTitle(CALIBRATION);
    expect(title).toContain('Out of sample since 2021');
    expect(title).toContain('ECE raw 0.0310 to 0.0390');
    expect(title).toContain('Brier raw 0.1200 to 0.1330; calibrated 0.1220 to 0.1360');
  });

  it('shows the compact line in the header', async () => {
    renderBadge();
    const badge = await screen.findByText('ECE 3.5%→1.7% · Brier 0.127→0.129');
    expect(badge).toHaveAttribute('title', expect.stringContaining('Out of sample since 2021'));
  });

  it('adds the out-of-sample note on the spreads page', async () => {
    renderBadge('full');
    expect(
      await screen.findByText('ECE 3.5%→1.7% · Brier 0.127→0.129 (out of sample, 2021+)'),
    ).toBeInTheDocument();
  });

  it('renders nothing when the metrics are missing', async () => {
    server.use(
      http.get('/api/calibration/summary', () =>
        HttpResponse.json({ ...CALIBRATION, metrics: [] }),
      ),
    );
    expect(calibrationText({ ...CALIBRATION, metrics: [] })).toBeNull();
    const { container } = renderBadge();
    // Let the query settle, then confirm nothing was drawn.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container).toBeEmptyDOMElement();
  });
});
