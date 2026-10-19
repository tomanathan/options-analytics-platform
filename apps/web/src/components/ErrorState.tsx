import { ApiError, DEFAULT_RETRY_AFTER_S } from '../api/client';

interface ErrorStateProps {
  error: unknown;
  /** `banner` sits above content that is still visible; `block` replaces it. */
  variant?: 'block' | 'banner';
  onRetry?: () => void;
}

/** User-facing text for an API failure (design spec section 5.4). */
export function ErrorState({ error, variant = 'block', onRetry }: ErrorStateProps) {
  const className = variant === 'banner' ? 'notice notice--banner' : 'notice';

  if (error instanceof ApiError && error.code === 'database_busy') {
    const seconds = error.retryAfterS ?? DEFAULT_RETRY_AFTER_S;
    return (
      <div className={className} role="status">
        <span aria-hidden="true">{'⧗'}</span> dbt is writing the database. Retrying in {seconds} s
        {'…'}
      </div>
    );
  }
  if (error instanceof ApiError && error.code === 'database_missing') {
    return (
      <div className={className} role="alert">
        No gold data yet: run <code>make dbt-build-local</code>
      </div>
    );
  }
  if (error instanceof ApiError && error.code === 'gold_missing') {
    return (
      <div className={className} role="alert">
        The gold tables are missing: run <code>make dbt-build-local</code>
      </div>
    );
  }
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  return (
    <div className={className} role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
