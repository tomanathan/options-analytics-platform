import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { DEFAULT_RETRY_AFTER_S, useDataStatus } from '../api/client';

/**
 * Header status. While the API serves cached data because dbt holds the database, say so and
 * re-check periodically so fresh data replaces it once the write finishes.
 */
export function DataStatus() {
  const { stale } = useDataStatus();
  const client = useQueryClient();

  useEffect(() => {
    if (!stale) return undefined;
    const id = window.setInterval(() => {
      void client.invalidateQueries();
    }, DEFAULT_RETRY_AFTER_S * 1000);
    return () => window.clearInterval(id);
  }, [stale, client]);

  if (!stale) return null;
  return (
    <span className="status status--stale" role="status">
      <span aria-hidden="true">{'⚠'}</span> Showing cached data while dbt writes
    </span>
  );
}
