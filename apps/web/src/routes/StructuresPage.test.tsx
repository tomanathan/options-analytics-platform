import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { createQueryClient } from '../api/queries';
import { LATEST_SESSION, makeDistribution } from '../test/fixtures';
import { requestLog, server } from '../test/server';
import { ADVICE_WORDS } from '../test/wording';
import StructuresPage from './StructuresPage';

const clients: ReturnType<typeof createQueryClient>[] = [];

function Location() {
  return <output data-testid="search">{useLocation().search}</output>;
}

function renderPage(entry = '/structures') {
  const client = createQueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <StructuresPage />
        <Location />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Requests of the structures endpoint, parsed. */
const structureRequests = () =>
  requestLog
    .filter((url) => /\/api\/structures\/(?!map)/.test(url))
    .map((url) => new URL(url, 'http://localhost'));
const lastRequest = () => structureRequests()[structureRequests().length - 1];

const kindsTable = () => screen.getByRole('table', { name: 'Best structure of each kind' });

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

describe('StructuresPage', () => {
  it('asks for the latest SPY session with the default preset and renders every panel', async () => {
    renderPage();
    expect(await screen.findByTestId('verdict-headline')).toHaveTextContent(
      'For this outcome, the bull call spread serves best',
    );
    const url = lastRequest();
    expect(url?.pathname).toBe(`/api/structures/SPY/${LATEST_SESSION}`);
    expect(Object.fromEntries(url?.searchParams ?? [])).toEqual({
      preset: 'up_moderate',
      fill: 'natural',
      map: 'auto',
      min_pop_given: '0.5',
      limit: '25',
    });

    expect(screen.getByTestId('view-sentence')).toHaveTextContent(
      /^Above \$517\.46 and below \$548\.20: 30\.0% calibrated, 27\.0% market-implied\.$/,
    );
    expect(screen.getByRole('button', { name: 'Up, moderately (55th to 85th)' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    // Seven kinds qualify in the fixture; the table starts at the highest return if right.
    const rows = within(kindsTable()).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(7);
    expect(rows[0]).toHaveTextContent('Bull call spread');
    expect(rows[0]).toHaveTextContent('1.74×');
    expect(within(kindsTable()).getAllByText('∞', { selector: 'td' })).toHaveLength(2);
    expect(within(kindsTable()).getAllByText('tail').length).toBeGreaterThan(0);
    // The chart draws a line per kind with the verdict's best kind selected.
    expect(await screen.findByTestId('kind-line-bull_call_spread')).toHaveAttribute(
      'data-selected',
      'true',
    );
    expect(screen.getAllByTestId('dominance-segment').length).toBeGreaterThan(0);
    // Tiles: P(view) against the market, and the scored counts.
    expect(screen.getByText('market 27.0% · +3.0 pts')).toBeInTheDocument();
    expect(screen.getByText('qualifying of 2,140 scored')).toBeInTheDocument();
    // The detail panel describes the selected kind.
    expect(
      screen.getByRole('heading', { name: 'Bull call spread · +1 C 515 / -1 C 530' }),
    ).toBeInTheDocument();
  });

  it('changes the query key when a control changes', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('verdict-headline');

    await user.click(screen.getByRole('radio', { name: 'Mid' }));
    await waitFor(() => expect(lastRequest()?.searchParams.get('fill')).toBe('mid'));
    expect(screen.getByTestId('search')).toHaveTextContent('fill=mid');

    await user.click(screen.getByRole('radio', { name: 'Production' }));
    await waitFor(() => expect(lastRequest()?.searchParams.get('map')).toBe('production'));

    await user.selectOptions(screen.getByLabelText('Expiration'), '2026-10-23');
    await waitFor(() => expect(lastRequest()?.searchParams.get('expiration')).toBe('2026-10-23'));

    await user.selectOptions(screen.getByLabelText('Session'), '2026-09-29');
    await waitFor(() => expect(lastRequest()?.pathname).toBe('/api/structures/SPY/2026-09-29'));
    // A new session forgets the expiration and lets the API pick again.
    expect(lastRequest()?.searchParams.has('expiration')).toBe(false);

    await user.selectOptions(screen.getByLabelText('Underlying'), 'XLF');
    await waitFor(() => expect(lastRequest()?.pathname).toMatch(/^\/api\/structures\/XLF\//));
  });

  it('fills the range inputs from a preset and switches to custom when one is edited', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('verdict-headline');

    await user.click(screen.getByRole('button', { name: 'Flat (25th to 75th)' }));
    await waitFor(() => expect(lastRequest()?.searchParams.get('preset')).toBe('flat'));
    const lo = screen.getByLabelText('lo % of close');
    const hi = screen.getByLabelText('hi % of close');
    await waitFor(() => expect(lo).toHaveValue(95));
    expect(hi).toHaveValue(105);
    expect(screen.getByTestId('outcome-mode')).toHaveTextContent('preset bounds');

    await user.clear(lo);
    await user.type(lo, '97{Enter}');
    await waitFor(() => expect(lastRequest()?.searchParams.has('preset')).toBe(false));
    expect(lastRequest()?.searchParams.get('lo')).toBe('0.97');
    expect(lastRequest()?.searchParams.get('hi')).toBe('1.05');
    expect(screen.getByTestId('outcome-mode')).toHaveTextContent('custom range');
    expect(screen.getByTestId('search')).toHaveTextContent('lo=0.97&hi=1.05');
    screen
      .getAllByRole('button', { pressed: false })
      .forEach((button) => expect(button).toHaveAttribute('aria-pressed', 'false'));
    expect(screen.queryByRole('button', { pressed: true })).toBeNull();

    await user.click(screen.getByRole('switch', { name: 'Outside' }));
    await waitFor(() => expect(lastRequest()?.searchParams.get('outside')).toBe('true'));
    expect(await screen.findAllByTestId('view-shade')).toHaveLength(2);
  });

  it('selects a kind from the table and shows its legs in the detail panel', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('verdict-headline');
    const row = within(kindsTable()).getByRole('row', { name: /Long call/ });
    await user.click(row);
    expect(screen.getByTestId('search')).toHaveTextContent('kind=long_call');
    expect(
      await screen.findByRole('heading', { name: 'Long call · +1 C 520' }),
    ).toBeInTheDocument();
    const legs = screen.getByRole('table', { name: 'Legs of the Long call' });
    expect(within(legs).getByText('ask')).toBeInTheDocument();
    expect(await screen.findByTestId('kind-line-long_call')).toHaveAttribute(
      'data-selected',
      'true',
    );
    const detail = screen.getByRole('region', { name: 'Structure detail' });
    expect(within(detail).getAllByText('$620.00').length).toBeGreaterThan(0);
  });

  it('lists every qualifying structure in a collapsible table', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('verdict-headline');
    const summary = screen.getByText('All qualifying structures (7)');
    await user.click(summary);
    const table = screen.getByRole('table', { name: 'All qualifying structures' });
    expect(within(table).getAllByRole('row')).toHaveLength(8);
  });

  it('disables expirations without a curve and names the reason', async () => {
    server.use(
      http.get('/api/underlyings/:symbol/sessions/:session/distribution', ({ params }) => {
        const body = makeDistribution(String(params.session), 'auto', String(params.symbol));
        const first = body.expirations[0];
        if (first) {
          first.curve = null;
          first.unavailable_reason = 'too_few_puts';
        }
        return HttpResponse.json(body);
      }),
    );
    renderPage();
    const option = await screen.findByRole('option', { name: /Oct 9 · 7d · too_few_puts/ });
    expect(option).toBeDisabled();
    expect(screen.getByRole('option', { name: 'Oct 16 · 14d' })).not.toBeDisabled();
  });

  it('shows the API reason when the custom range is invalid', async () => {
    renderPage('/structures?lo=1.1&hi=1.0');
    expect(
      await screen.findByText('The lower bound must be below the upper bound.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('lo % of close')).toHaveValue(110);
  });

  it('uses no buy, sell, recommend or should wording anywhere on the page', async () => {
    const user = userEvent.setup();
    renderPage('/structures?kind=iron_condor');
    await screen.findByTestId('verdict-headline');
    await user.click(screen.getByText(/^All qualifying structures \(/));
    expect(document.body.textContent).not.toMatch(ADVICE_WORDS);
  });
});
