import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { createQueryClient } from '../api/queries';
import { requestLog } from '../test/server';
import SpreadsPage from './SpreadsPage';

const clients: ReturnType<typeof createQueryClient>[] = [];

function Location() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderPage(entry = '/spreads') {
  const client = createQueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <SpreadsPage />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const summary = () => document.querySelector('.summary')?.textContent ?? '';

const spreadRequests = () => requestLog.filter((url) => /\/api\/spreads\?/.test(url));

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

describe('SpreadsPage', () => {
  it('asks for eligible spreads by default and lists them in rank order', async () => {
    renderPage();
    expect(await screen.findByText(/of 9 spreads/)).toBeInTheDocument();
    const url = new URL(spreadRequests()[0] ?? '', 'http://localhost');
    expect(url.searchParams.get('eligible_only')).toBe('true');
    expect(url.searchParams.get('min_pop')).toBe('0');
    expect(url.searchParams.get('min_credit')).toBe('0');

    const table = screen.getByRole('table', { name: 'Put credit spreads' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(7);
    expect(within(rows[0] as HTMLElement).getByText('370/367.5')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('58.1%')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('51.1%')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('14.38%')).toBeInTheDocument();
  });

  it('highlights the underlyings of the rank 1 to 3 rows by default', async () => {
    renderPage();
    await screen.findByText(/of 9 spreads/);
    expect(
      await screen.findByRole('button', { name: /Highlight: TSLA, MSFT/ }),
    ).toBeInTheDocument();
    expect(await screen.findByText('Other')).toBeInTheDocument();
  });

  it('sends the new filter to the API and the URL when a filter changes', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 9 spreads/);
    const before = spreadRequests().length;

    await user.click(screen.getByRole('switch', { name: 'Eligible only' }));

    await waitFor(() => expect(spreadRequests().length).toBeGreaterThan(before));
    const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
    expect(latest.searchParams.get('eligible_only')).toBe('false');
    expect(screen.getByTestId('search')).toHaveTextContent('elig=0');
    await waitFor(() => expect(summary()).toMatch(/^9 of 9 spreads/));
    // The two extreme rows are pinned to the plot edge.
    expect(screen.getByTestId('pinned-note')).toHaveTextContent('2 points beyond');
  });

  it('commits a width filter on blur', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 9 spreads/);
    await user.type(screen.getByLabelText('Min width ($)'), '5');
    await user.tab();
    await waitFor(() => {
      const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
      expect(latest.searchParams.get('min_width')).toBe('5');
    });
    await waitFor(() => expect(summary()).toMatch(/^5 of 9 spreads/));
  });

  it('opens the detail panel when a row is selected', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 9 spreads/);
    expect(screen.getByText('Select a spread')).toBeInTheDocument();

    await user.click(screen.getByRole('row', { name: /TSLA.*370\/367\.5/ }));

    expect(
      await screen.findByRole('heading', { name: 'TSLA 370/367.5 · Oct 16 · 14d' }),
    ).toBeInTheDocument();
    expect(requestLog).toContain(
      'http://localhost:3000/api/spreads/TSLA%7C2026-10-16%7C370%7C367.5',
    );
    expect(screen.getByTestId('search')).toHaveTextContent('sel=TSLA%7C2026-10-16%7C370%7C367.5');
    const panel = screen.getByRole('region', { name: 'Spread detail' });
    expect(await within(panel).findByText('Breakeven')).toBeInTheDocument();
    expect(within(panel).getByText('Max loss')).toBeInTheDocument();
    expect(within(panel).getByText('P(max loss)')).toBeInTheDocument();
    expect(within(panel).getByText('Kelly')).toBeInTheDocument();
    expect(await within(panel).findByTestId('payoff-line')).toBeInTheDocument();
    expect(within(panel).getByText(/P\(profit\) 58\.1%/)).toBeInTheDocument();
    expect(within(panel).getByText(/P\(loss\) 41\.9%/)).toBeInTheDocument();
  });

  it('shows interest per contract and labels the units of the money tiles', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 9 spreads/);
    await user.click(screen.getByRole('row', { name: /TSLA.*370\/367\.5/ }));
    const panel = screen.getByRole('region', { name: 'Spread detail' });
    await within(panel).findByText('Breakeven');

    const tile = (label: string) => within(panel).getByText(label).closest('.stat') as HTMLElement;
    // 0.0017 $/sh is 17 cents per 100-share contract, not "$0.00".
    expect(tile('Interest')).toHaveTextContent('$0.17');
    expect(tile('Interest')).toHaveTextContent('per contract');
    expect(tile('Interest')).not.toHaveTextContent('$0.00');
    ['Credit', 'Max loss', 'Breakeven'].forEach((label) => {
      expect(tile(label)).toHaveTextContent('$/sh');
    });
  });

  it('restores a selection from the URL', async () => {
    renderPage('/spreads?sel=MSFT%7C2026-10-16%7C510%7C505');
    expect(
      await screen.findByRole('heading', { name: 'MSFT 510/505 · Oct 16 · 14d' }),
    ).toBeInTheDocument();
  });

  it('shows the calibration badge with the out-of-sample note', async () => {
    renderPage();
    expect(
      await screen.findByText(/ECE 3\.5%→1\.7% · Brier 0\.127→0\.129 \(out of sample, 2021\+\)/),
    ).toBeInTheDocument();
  });
});
