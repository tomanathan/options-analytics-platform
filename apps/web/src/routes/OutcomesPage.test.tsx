import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { createQueryClient } from '../api/queries';
import { advantageColor } from '../lib/structures';
import { LATEST_SESSION } from '../test/fixtures';
import { requestLog } from '../test/server';
import { STRUCTURE_EXPIRATION } from '../test/structureFixtures';
import { ADVICE_WORDS } from '../test/wording';
import OutcomesPage from './OutcomesPage';

const clients: ReturnType<typeof createQueryClient>[] = [];

function Landed() {
  const location = useLocation();
  return <output data-testid="landed">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(entry = '/outcomes') {
  const client = createQueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/outcomes" element={<OutcomesPage />} />
          <Route path="/structures" element={<Landed />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const mapRequests = () =>
  requestLog
    .filter((url) => url.includes('/api/structures/map'))
    .map((url) => new URL(url, 'http://localhost'));
const lastMapRequest = () => mapRequests()[mapRequests().length - 1];

const matrix = () =>
  screen.getByRole('table', { name: /Best structure kind by underlying and outcome/ });

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

describe('OutcomesPage', () => {
  it('asks for the latest session at 35 days and draws tickers by six presets', async () => {
    renderPage();
    await screen.findByRole('table', { name: /Best structure kind/ });
    expect(Object.fromEntries(lastMapRequest()?.searchParams ?? [])).toEqual({
      session: 'latest',
      target_dte: '35',
      fill: 'natural',
      map: 'auto',
      min_pop_given: '0.5',
    });

    const headers = within(matrix()).getAllByRole('columnheader');
    expect(headers.map((h) => h.textContent)).toEqual([
      'Underlying',
      'Up, above the 75th percentile',
      'Up, moderately (55th to 85th)',
      'Flat (25th to 75th)',
      'Down, moderately (15th to 45th)',
      'Down, below the 25th percentile',
      'Big move, outside the 10th to 90th',
    ]);
    const rows = within(matrix()).getAllByRole('row').slice(1);
    // Rows sorted by symbol; the ticker without an expiration spans the row with its reason.
    expect(rows.map((row) => within(row).getByRole('rowheader').firstChild?.textContent)).toEqual([
      'QQQ',
      'SPY',
      'XLF',
    ]);
    expect(rows[0]).toHaveTextContent('no expiration with a curve at 7 days or more');
    expect(within(rows[1] as HTMLElement).getAllByRole('link')).toHaveLength(6);
    expect(within(rows[2] as HTMLElement).getAllByRole('link')).toHaveLength(6);
  });

  it('shows the best kind and its return, coloured by the advantage', async () => {
    renderPage();
    await screen.findByRole('table', { name: /Best structure kind/ });
    const spy = screen.getByTestId('matrix-row-SPY');
    const cells = within(spy).getAllByRole('cell');
    expect(cells[0]).toHaveTextContent('↑ Call2.90×');
    expect(cells[1]).toHaveTextContent('↑ Bull call1.74×');
    expect(cells[5]).toHaveTextContent('none qualifies');
    // Spreads ahead is cool, singles ahead warm, a missing side grey.
    expect(cells[1]?.style.background).not.toBe('');
    expect(cells[0]).toHaveAttribute('data-advantage', '-0.8');
    expect(cells[1]).toHaveAttribute('data-advantage', '0.53');
    expect(advantageColor(0.53)).not.toBe(advantageColor(-0.8));
    expect(screen.getByTestId('advantage-legend')).toHaveTextContent('spreads return more');
    expect(screen.getByTestId('outcome-footer')).toHaveTextContent(
      'Session Oct 2, 2026 · expiration nearest 35 days (at least 7) · natural fill · map production',
    );
  });

  it('shows the full cell on hover', async () => {
    renderPage();
    await screen.findByRole('table', { name: /Best structure kind/ });
    const link = within(screen.getByTestId('matrix-row-XLF')).getAllByRole('link')[1];
    fireEvent.mouseEnter(link as HTMLElement);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('Above $517.46 and below $548.20');
    expect(tooltip).toHaveTextContent('25.0%calibrated');
    expect(tooltip).toHaveTextContent('1.74×spread: bull call spread');
    expect(tooltip).toHaveTextContent('1.21×single: long call');
    expect(tooltip).toHaveTextContent('+0.53×for the spread, if right');
    expect(tooltip).toHaveTextContent(
      'XLF · Up, moderately (55th to 85th) · best +1 C 515 / -1 C 530',
    );
  });

  it('links each cell to the structures page in the same state', async () => {
    const user = userEvent.setup();
    renderPage('/outcomes?fill=mid&map=production');
    await screen.findByRole('table', { name: /Best structure kind/ });
    const link = within(screen.getByTestId('matrix-row-SPY')).getByRole('link', {
      name: /Down, below the 25th percentile/,
    });
    expect(link).toHaveAttribute(
      'href',
      `/structures?symbol=SPY&session=${LATEST_SESSION}&expiration=${STRUCTURE_EXPIRATION}&preset=down&fill=mid&map=production`,
    );
    await user.click(link);
    expect(screen.getByTestId('landed')).toHaveTextContent(
      `/structures?symbol=SPY&session=${LATEST_SESSION}&expiration=${STRUCTURE_EXPIRATION}&preset=down&fill=mid&map=production`,
    );
  });

  it('sends the target DTE and session to the API', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole('table', { name: /Best structure kind/ });
    const dte = screen.getByLabelText('Target DTE (days)');
    await user.clear(dte);
    await user.type(dte, '60{Enter}');
    await waitFor(() => expect(lastMapRequest()?.searchParams.get('target_dte')).toBe('60'));
    await user.selectOptions(screen.getByLabelText('Session'), '2026-09-29');
    await waitFor(() => expect(lastMapRequest()?.searchParams.get('session')).toBe('2026-09-29'));
    await user.clear(dte);
    await user.type(dte, '500{Enter}');
    await waitFor(() => expect(lastMapRequest()?.searchParams.get('target_dte')).toBe('120'));
  });

  it('uses no buy, sell, recommend or should wording', async () => {
    renderPage();
    await screen.findByRole('table', { name: /Best structure kind/ });
    fireEvent.mouseEnter(within(screen.getByTestId('matrix-row-SPY')).getAllByRole('link')[0]!);
    expect(document.body.textContent).not.toMatch(ADVICE_WORDS);
  });
});
