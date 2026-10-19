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

/** A row of the main spreads table (the entry card repeats some of the same spreads). */
const tableRow = (name: RegExp) =>
  within(screen.getByRole('table', { name: 'Put credit spreads' })).getByRole('row', { name });

const summary = () => document.querySelector('.summary')?.textContent ?? '';

/** Requests of the page's own list; the entry card asks for its own ten rows (limit=10). */
const spreadRequests = () =>
  requestLog.filter((url) => /\/api\/spreads\?/.test(url) && !url.includes('limit=10'));

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

describe('SpreadsPage', () => {
  it('asks for eligible spreads by default and lists them in rank order', async () => {
    renderPage();
    expect(await screen.findByText(/of 14 spreads/)).toBeInTheDocument();
    const url = new URL(spreadRequests()[0] ?? '', 'http://localhost');
    expect(url.searchParams.get('eligible_only')).toBe('true');
    expect(url.searchParams.get('min_pop')).toBe('0');
    expect(url.searchParams.get('min_credit')).toBe('0');

    const table = screen.getByRole('table', { name: 'Put credit spreads' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(12);
    expect(within(rows[0] as HTMLElement).getByText('370/367.5')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('58.1%')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('51.1%')).toBeInTheDocument();
    expect(within(rows[0] as HTMLElement).getByText('14.38%')).toBeInTheDocument();
    expect(
      within(table).getByRole('columnheader', { name: /^E\[R\/max loss\]/ }),
    ).toBeInTheDocument();
    expect(
      within(table).getByRole('columnheader', { name: /^Ann\. R\/max loss/ }),
    ).toBeInTheDocument();
    expect(within(table).queryByText(/ROC/)).not.toBeInTheDocument();
  });

  it('highlights the underlyings of the rank 1 to 3 rows by default', async () => {
    renderPage();
    await screen.findByText(/of 14 spreads/);
    expect(
      await screen.findByRole('button', { name: /Highlight: TSLA, MSFT/ }),
    ).toBeInTheDocument();
    expect((await screen.findAllByText('Other')).length).toBeGreaterThan(0);
  });

  it('sends the new filter to the API and the URL when a filter changes', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    const before = spreadRequests().length;

    await user.click(screen.getByRole('switch', { name: 'Eligible only' }));

    await waitFor(() => expect(spreadRequests().length).toBeGreaterThan(before));
    const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
    expect(latest.searchParams.get('eligible_only')).toBe('false');
    expect(screen.getByTestId('search')).toHaveTextContent('elig=0');
    await waitFor(() => expect(summary()).toMatch(/^14 of 14 spreads/));
    // The two extreme rows are pinned to the plot edge.
    expect(screen.getByTestId('pinned-note')).toHaveTextContent('2 points beyond');
  });

  it('commits a width filter on blur', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    await user.type(screen.getByLabelText('Min width ($)'), '5');
    await user.tab();
    await waitFor(() => {
      const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
      expect(latest.searchParams.get('min_width')).toBe('5');
    });
    await waitFor(() => expect(summary()).toMatch(/^8 of 14 spreads/));
  });

  it('opens the detail panel when a row is selected', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    expect(screen.getByText('Select a spread')).toBeInTheDocument();

    await user.click(tableRow(/TSLA.*370\/367\.5/));

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
    expect(within(panel).getByText('Exp. return on max loss')).toBeInTheDocument();
    expect(within(panel).queryByText(/ROC|collateral/)).not.toBeInTheDocument();
    expect(await within(panel).findByTestId('payoff-line')).toBeInTheDocument();
    expect(within(panel).getByText(/P\(profit\) 58\.1%/)).toBeInTheDocument();
    expect(within(panel).getByText(/P\(loss\) 41\.9%/)).toBeInTheDocument();
  });

  it('shows interest per contract and labels the units of the money tiles', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    await user.click(tableRow(/TSLA.*370\/367\.5/));
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

  it('ranks by edge: sends sort=edge, writes by=edge, retitles and reorders the table', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    const table = () => screen.getByRole('table', { name: 'Put credit spreads' });
    expect(
      within(table()).getByRole('columnheader', { name: /^Rank · Return on max loss/ }),
    ).toBeInTheDocument();
    expect(new URL(spreadRequests()[0] ?? '', 'http://localhost').searchParams.get('sort')).toBe(
      'return',
    );

    await user.click(screen.getByRole('radio', { name: 'Edge' }));

    await waitFor(() => {
      const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
      expect(latest.searchParams.get('sort')).toBe('edge');
    });
    expect(screen.getByTestId('search')).toHaveTextContent('by=edge');
    await waitFor(() =>
      expect(
        within(table()).getByRole('columnheader', { name: /^Rank · Edge/ }),
      ).toBeInTheDocument(),
    );
    const first = within(table()).getAllByRole('row')[1] as HTMLElement;
    // The fixtures give the largest edge share to the return rank 5 row, XLF 52/51.
    expect(within(first).getByText('52/51')).toBeInTheDocument();
    expect(within(first).getAllByRole('cell')[0]).toHaveTextContent('1');
  });

  it('keeps the # column on the server order when a header is clicked', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    const table = screen.getByRole('table', { name: 'Put credit spreads' });
    await user.click(within(table).getByRole('button', { name: /^Fair credit/ }));
    const rows = within(table).getAllByRole('row').slice(1);
    const positions = rows.map((r) => Number(within(r).getAllByRole('cell')[0]?.textContent));
    expect(positions).not.toEqual([...positions].sort((a, b) => a - b));
    expect([...positions].sort((a, b) => a - b)).toEqual(
      Array.from({ length: 12 }, (_, i) => i + 1),
    );
  });

  it.each([
    ['Reward/risk', 'reward_to_risk'],
    ['Kelly', 'kelly'],
    ['POP', 'pop'],
    ['POP gap', 'pop_gap'],
    ['Entry', 'entry'],
  ])('Rank by %s sends sort=%s', async (label, sort) => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    await user.click(screen.getByRole('radio', { name: label }));
    await waitFor(() => {
      const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
      expect(latest.searchParams.get('sort')).toBe(sort);
    });
    expect(screen.getByTestId('search')).toHaveTextContent(`by=${sort}`);
  });

  it('restores the ranking and the edge floor from the URL', async () => {
    renderPage('/spreads?by=pop_gap&edge=0.3');
    await screen.findByText(/of 14 spreads/);
    const query = spreadRequests().find((u) => u.includes('sort=pop_gap')) ?? '';
    expect(new URL(query, 'http://localhost').searchParams.get('min_edge_pct')).toBe('0.3');
    expect(screen.getByRole('radio', { name: 'POP gap' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByLabelText('Min edge (%)')).toHaveValue(30);
  });

  it('sends the minimum edge as a decimal share', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    await user.type(screen.getByLabelText('Min edge (%)'), '20');
    await user.tab();
    await waitFor(() => {
      const latest = new URL(spreadRequests().at(-1) ?? '', 'http://localhost');
      expect(latest.searchParams.get('min_edge_pct')).toBe('0.2');
    });
    expect(screen.getByTestId('search')).toHaveTextContent('edge=0.2');
    // Two eligible fixture rows have an edge share under 20%.
    await waitFor(() => expect(summary()).toMatch(/^10 of 14 spreads/));
  });

  it('shows the fair credit, edge and POP gap columns, with a dash for a missing reward/risk', async () => {
    renderPage();
    await screen.findByText(/of 14 spreads/);
    const table = screen.getByRole('table', { name: 'Put credit spreads' });
    [
      /^Fair credit/,
      /^Edge \$/,
      /^Edge %/,
      /^Reward\/risk/,
      /^Implied POP/,
      /^POP gap \(pts\)/,
    ].forEach((name) => {
      expect(within(table).getByRole('columnheader', { name })).toBeInTheDocument();
    });
    const first = within(tableRow(/TSLA.*370\/367\.5/));
    expect(first.getByText('0.56')).toBeInTheDocument(); // fair credit
    expect(first.getByText('22.0%')).toBeInTheDocument(); // edge share
    expect(first.getByText('-13.1')).toBeInTheDocument(); // POP gap, points
    expect(first.getByText('71.2%')).toBeInTheDocument(); // price-implied POP
    // MSFT 505/500 (return rank 6) has no reward/risk.
    const missing = tableRow(/MSFT.*505\/500/);
    expect(
      within(missing)
        .getAllByRole('cell')
        .some((cell) => cell.textContent === '–'),
    ).toBe(true);
  });

  it('shows the edge, dispersion and POP gap tiles and the interpretation line', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    await user.click(tableRow(/TSLA.*370\/367\.5/));
    const panel = screen.getByRole('region', { name: 'Spread detail' });
    await within(panel).findByText('Breakeven');
    const tile = (label: string) => within(panel).getByText(label).closest('.stat') as HTMLElement;
    expect(tile('Fair credit')).toHaveTextContent('$0.56');
    expect(tile('Fair credit')).toHaveTextContent('raw $0.60');
    expect(tile('Fair credit')).toHaveTextContent('$/sh');
    expect(tile('Edge')).toHaveTextContent('$0.16');
    expect(tile('Edge')).toHaveTextContent('22.0% of mid · natural $0.06');
    expect(tile('Payoff σ')).toHaveTextContent('$0.63');
    expect(tile('Reward/risk')).toHaveTextContent('0.25');
    expect(tile('Reward/risk')).toHaveTextContent('per trade, not annualised');
    expect(tile('Price-implied POP')).toHaveTextContent('71.2%');
    expect(tile('POP gap')).toHaveTextContent('-13.1');
    expect(tile('POP gap')).toHaveTextContent('raw gap -20.1 pts');
    expect(
      within(panel).getByText(
        /Fair credit applies one pooled calibration map to this chain: a historical average across today's large caps, not a forecast for this contract\./,
      ),
    ).toBeInTheDocument();
    expect(within(panel).queryByText(/natural credit the gap is negative/)).toBeNull();
  });

  it('adds the negative-gap sentence when the natural edge is below zero', async () => {
    renderPage('/spreads?sel=XLF%7C2026-10-16%7C51%7C50');
    await screen.findByText(/of 14 spreads/);
    const panel = screen.getByRole('region', { name: 'Spread detail' });
    expect(
      await within(panel).findByText(/At the natural credit the gap is negative\./),
    ).toBeInTheDocument();
  });

  it('draws the market-vs-fair and calibrated-vs-implied charts under the POP chart', async () => {
    renderPage();
    await screen.findByText(/of 14 spreads/);
    expect(
      screen.getByRole('heading', { name: 'Market vs calibrated fair credit' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Calibrated vs price-implied probability of profit' }),
    ).toBeInTheDocument();
    expect(await screen.findAllByTestId('parity-line')).toHaveLength(2);
    expect(
      screen.getByText(
        'The same information as the fair-credit chart, in probability units instead of dollars.',
      ),
    ).toBeInTheDocument();
  });

  it('highlights the underlyings of the first eligible rows in the active order', async () => {
    const user = userEvent.setup();
    renderPage('/spreads?by=edge');
    // Edge order starts XLF, SPY, MSFT, so those three are highlighted rather than TSLA.
    expect(
      await screen.findByRole('button', { name: /Highlight: XLF, SPY, MSFT/ }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Entry' }));
    expect(
      await screen.findByRole('button', { name: /Highlight: MSFT, SPY, TSLA/ }),
    ).toBeInTheDocument();
  });

  it('keeps the entry card on its own request when the filters change', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(/of 14 spreads/);
    const card = await screen.findByRole('region', { name: 'Top 10 to enter' });
    await within(card).findByRole('table');
    await user.click(screen.getByRole('radio', { name: 'Edge' }));
    await user.type(screen.getByLabelText('Min edge (%)'), '30');
    await user.tab();
    await waitFor(() => expect(summary()).toMatch(/^3 of 14 spreads/));
    const entryRequests = requestLog.filter(
      (u) => u.includes('sort=entry') && u.includes('limit=10'),
    );
    expect(entryRequests).toHaveLength(1);
    expect(within(card).getAllByRole('row')).toHaveLength(11);
  });

  it('selects a spread from the entry card and shows it in the detail panel', async () => {
    const user = userEvent.setup();
    renderPage();
    const card = await screen.findByRole('region', { name: 'Top 10 to enter' });
    const table = await within(card).findByRole('table');
    await user.click(within(table).getAllByRole('row')[1] as HTMLElement);
    expect(
      await screen.findByRole('heading', { name: 'MSFT 510/505 · Oct 16 · 14d' }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('search')).toHaveTextContent('sel=MSFT%7C2026-10-16%7C510%7C505');
  });

  it('prints the entry rule from the API in the first card of the page', async () => {
    renderPage();
    const rule = await screen.findByTestId('entry-rule');
    expect(rule).toHaveTextContent(/natural credit is at least half the mid/);
    expect(document.querySelector('.page > section')).toContainElement(rule);
  });

  it('uses no buy, sell or recommend wording anywhere on the page', async () => {
    const user = userEvent.setup();
    renderPage('/spreads?sel=TSLA%7C2026-10-16%7C370%7C367.5');
    await screen.findByText(/of 14 spreads/);
    const panel = screen.getByRole('region', { name: 'Spread detail' });
    await within(panel).findByText('Breakeven');
    await user.click(screen.getByRole('radio', { name: 'Edge' }));
    await screen.findByRole('columnheader', { name: /^Rank · Edge/ });
    expect(document.body.textContent).not.toMatch(/\b(buy|sell|recommend)\b/i);
    expect(document.body.textContent).not.toMatch(/overpriced|underpriced|mispriced/i);
  });
});
