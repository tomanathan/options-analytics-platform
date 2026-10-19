import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { createQueryClient } from '../api/queries';
import { LATEST_SESSION } from '../test/fixtures';
import { busyResponse, requestLog, server } from '../test/server';
import LandscapePage from './LandscapePage';

const clients: ReturnType<typeof createQueryClient>[] = [];

function renderPage(entry = '/landscape') {
  const client = createQueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[entry]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <LandscapePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  // Stop pending busy retries from leaking into the next test.
  clients.splice(0).forEach((client) => client.clear());
});

describe('LandscapePage', () => {
  it('renders the fixture session: four panels, heatmap, smile and chain', async () => {
    renderPage();

    const titles = await screen.findAllByRole('heading', { level: 3 });
    expect(titles.map((t) => t.textContent)).toEqual([
      'Oct 9 · 7d',
      'Oct 16 · 14d',
      'Oct 23 · 21d',
      'Nov 20 · 49d',
    ]);
    expect(screen.getAllByTestId('cdf-calibrated')).toHaveLength(4);
    expect(screen.getByText('F 512.73')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: /Probability heatmap/ })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Implied volatility smile/ })).toBeInTheDocument();

    const chain = screen.getByRole('table', { name: /Option chain for 2026-10-09/ });
    expect(within(chain).getByText('Calls')).toBeInTheDocument();
    expect(within(chain).getByText('Puts')).toBeInTheDocument();
    // One quote is unusable and muted with an explanation.
    expect(chain.querySelector('[title="excluded: zero bid or crossed"]')).not.toBeNull();
    // The at-the-money row is highlighted.
    expect(chain.querySelector('tr.is-atm')).not.toBeNull();
  });

  it('loads the latest session of SPY with the auto map', async () => {
    renderPage();
    await screen.findAllByRole('heading', { level: 3 });
    expect(requestLog.some((url) => url.endsWith('/api/underlyings/SPY/sessions'))).toBe(true);
    expect(
      requestLog.some((url) =>
        url.endsWith(`/api/underlyings/SPY/sessions/${LATEST_SESSION}/distribution?map=auto`),
      ),
    ).toBe(true);
    expect(screen.getByLabelText('Session date')).toHaveAttribute('aria-valuetext', 'Oct 2, 2026');
    expect(screen.getByText('map: production')).toBeInTheDocument();
  });

  it('honours d and map from the URL', async () => {
    renderPage('/landscape?d=2026-09-28&map=walk_forward');
    await screen.findByText('map: fold_2026');
    expect(
      requestLog.some((url) => url.includes('/sessions/2026-09-28/distribution?map=walk_forward')),
    ).toBe(true);
  });

  it('shows the busy message and keeps retrying while the database is locked', async () => {
    server.use(
      http.get('/api/underlyings/:symbol/sessions/:session/distribution', () => busyResponse(15)),
    );
    renderPage();
    expect(
      await screen.findByText(/dbt is writing the database\. Retrying in 15 s/),
    ).toBeInTheDocument();
    // The rest of the page is still usable.
    expect(await screen.findByRole('table', { name: /Option chain/ })).toBeInTheDocument();
  });

  it('says what to run when there is no gold data yet', async () => {
    server.use(
      http.get('/api/underlyings/:symbol/sessions', () =>
        Response.json(
          { detail: 'run make dbt-build-local', code: 'database_missing' },
          { status: 503 },
        ),
      ),
    );
    renderPage();
    expect(await screen.findByText(/No gold data yet: run/)).toBeInTheDocument();
    expect(screen.getByText('make dbt-build-local')).toBeInTheDocument();
  });

  it('reports a 404 for an unknown underlying', async () => {
    server.use(
      http.get('/api/underlyings/:symbol/sessions', () =>
        Response.json({ detail: 'Unknown underlying ZZZ', code: 'not_found' }, { status: 404 }),
      ),
    );
    renderPage('/landscape?u=ZZZ');
    await waitFor(() => expect(screen.getByText('Unknown underlying ZZZ')).toBeInTheDocument());
  });
});
