import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createQueryClient } from '../api/queries';
import { makeSpreads, SPREAD_ROWS } from '../test/fixtures';
import { requestLog, server } from '../test/server';
import { EntryCard } from './EntryCard';

const clients: ReturnType<typeof createQueryClient>[] = [];

function renderCard(selectedKey: string | null = null) {
  const client = createQueryClient();
  clients.push(client);
  const onSelect = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <EntryCard selectedKey={selectedKey} onSelect={onSelect} />
    </QueryClientProvider>,
  );
  return { onSelect };
}

afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

const bodyRows = () =>
  within(screen.getByRole('table', { name: 'Top 10 spreads to enter' }))
    .getAllByRole('row')
    .slice(1);

describe('EntryCard', () => {
  it('asks for the entry order over eligible spreads, ten rows, with no page filters', async () => {
    renderCard();
    await screen.findByRole('table', { name: 'Top 10 spreads to enter' });
    const url = new URL(requestLog.find((u) => u.includes('/api/spreads?')) ?? '');
    expect(url.searchParams.get('sort')).toBe('entry');
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('eligible_only')).toBe('true');
    expect(url.searchParams.has('underlying')).toBe(false);
    expect(url.searchParams.has('min_edge_pct')).toBe(false);
  });

  it('renders ten rows in rank_entry order', async () => {
    renderCard();
    await screen.findByRole('table', { name: 'Top 10 spreads to enter' });
    const rows = bodyRows();
    expect(rows).toHaveLength(10);
    const expected = SPREAD_ROWS.filter((r) => r.rank_entry !== null)
      .sort((a, b) => (a.rank_entry ?? 0) - (b.rank_entry ?? 0))
      .slice(0, 10);
    rows.forEach((tr, index) => {
      const cells = within(tr).getAllByRole('cell');
      const row = expected[index];
      expect(cells[0]).toHaveTextContent(String(index + 1));
      expect(cells[1]).toHaveTextContent(row?.underlying ?? '');
    });
    // The fixtures give the best entry rank to the rank 2 row (MSFT 510/505).
    expect(within(rows[0] as HTMLElement).getByText('510/505')).toBeInTheDocument();
  });

  it('shows the columns the card promises', async () => {
    renderCard();
    const table = await screen.findByRole('table', { name: 'Top 10 spreads to enter' });
    [
      '#',
      'Underlying',
      'Exp (DTE)',
      'Short/Long',
      'Natural',
      'POP cal',
      'E[R/max loss]',
      'Ann. R/max loss',
      'Edge %',
      'Reward/risk',
    ].forEach((name) => {
      expect(within(table).getByRole('columnheader', { name })).toBeInTheDocument();
    });
    const first = within(bodyRows()[0] as HTMLElement);
    expect(first.getByText('Oct 16 · 14d')).toBeInTheDocument();
    expect(first.getByText('0.94')).toBeInTheDocument(); // natural credit
    expect(first.getByText('68.0%')).toBeInTheDocument(); // POP calibrated
    expect(first.getByText('13.00%')).toBeInTheDocument(); // expected return on max loss
    expect(first.getByText('31.0%')).toBeInTheDocument(); // edge %
  });

  it('prints the entry rule from the response under the heading, verbatim', async () => {
    const rule = 'Rule text from the API: eligible, natural credit at least half the mid.';
    server.use(
      http.get('/api/spreads', () =>
        HttpResponse.json({
          ...makeSpreads({
            underlyings: [],
            expiration: null,
            minWidth: null,
            maxWidth: null,
            minPop: 0,
            minCredit: 0,
            eligibleOnly: true,
            sort: 'entry',
            limit: 10,
          }),
          entry_rule: rule,
        }),
      ),
    );
    renderCard();
    expect(await screen.findByTestId('entry-rule')).toHaveTextContent(rule);
    expect(screen.getByTestId('entry-rule').textContent).toBe(rule);
    const heading = screen.getByRole('heading', { name: 'Top 10 to enter' });
    const rulePara = screen.getByTestId('entry-rule');
    expect(
      heading.compareDocumentPosition(rulePara) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('carries the caveat that this is a ranking, not advice', async () => {
    renderCard();
    expect(
      await screen.findByText('A ranking of historical calibration, not trade advice.'),
    ).toBeInTheDocument();
  });

  it('selects the spread when a row is clicked or Enter is pressed', async () => {
    const user = userEvent.setup();
    const { onSelect } = renderCard();
    await screen.findByRole('table', { name: 'Top 10 spreads to enter' });
    await user.click(bodyRows()[2] as HTMLElement);
    const third = SPREAD_ROWS.find((r) => r.rank_entry === 3);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0].spread_key).toBe(third?.spread_key);

    (bodyRows()[0] as HTMLElement).focus();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect.mock.calls[1]?.[0].rank_entry).toBe(1);
  });

  it('marks the selected spread', async () => {
    const first = SPREAD_ROWS.find((r) => r.rank_entry === 1);
    renderCard(first?.spread_key ?? null);
    await screen.findByRole('table', { name: 'Top 10 spreads to enter' });
    expect(bodyRows()[0]).toHaveAttribute('aria-selected', 'true');
    expect(bodyRows()[1]).toHaveAttribute('aria-selected', 'false');
  });

  it('shows an empty state when no row passes the rule', async () => {
    server.use(
      http.get('/api/spreads', () =>
        HttpResponse.json({
          ...makeSpreads({
            underlyings: [],
            expiration: null,
            minWidth: null,
            maxWidth: null,
            minPop: 0,
            minCredit: 0,
            eligibleOnly: true,
            sort: 'entry',
            limit: 10,
          }),
          matched: 0,
          rows: [],
        }),
      ),
    );
    renderCard();
    expect(await screen.findByText('No spread passes the entry rule')).toBeInTheDocument();
    expect(screen.queryByRole('table')).toBeNull();
    // The rule and the caveat stay visible so the reader knows what was asked.
    expect(screen.getByTestId('entry-rule')).toBeInTheDocument();
    expect(screen.getByText(/not trade advice/)).toBeInTheDocument();
  });
});
