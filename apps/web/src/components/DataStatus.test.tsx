import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { fetchJson } from '../api/client';
import { UNDERLYINGS } from '../test/fixtures';
import { server } from '../test/server';
import { DataStatus } from './DataStatus';

function renderStatus() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DataStatus />
    </QueryClientProvider>,
  );
}

describe('DataStatus', () => {
  it('is silent while data is fresh', () => {
    renderStatus();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('says cached data is shown while dbt writes, and goes away when fresh data returns', async () => {
    renderStatus();
    server.use(
      http.get('/api/underlyings', () =>
        HttpResponse.json(UNDERLYINGS, { headers: { 'X-OAP-Data-Stale': '1' } }),
      ),
    );
    await act(async () => {
      await fetchJson('/api/underlyings');
    });
    expect(screen.getByRole('status')).toHaveTextContent('Showing cached data while dbt writes');

    server.resetHandlers();
    await act(async () => {
      await fetchJson('/api/underlyings');
    });
    expect(screen.queryByRole('status')).toBeNull();
  });
});
