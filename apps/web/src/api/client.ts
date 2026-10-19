import { useSyncExternalStore } from 'react';
import type { ErrorBody, ErrorCode } from './types';

/** Fallback wait when a 503 carries no usable `Retry-After` header (seconds). */
export const DEFAULT_RETRY_AFTER_S = 15;

/** A non-2xx API response. `code` is the API's error code, `retryAfterS` comes from `Retry-After`. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | null;
  readonly retryAfterS: number | null;

  constructor(status: number, message: string, code: ErrorCode | null, retryAfterS: number | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterS = retryAfterS;
  }
}

export interface DataStatus {
  /** True while the latest response was served from cache because dbt holds the database. */
  stale: boolean;
}

let status: DataStatus = { stale: false };
const listeners = new Set<() => void>();

function setStale(stale: boolean): void {
  if (status.stale === stale) return;
  status = { stale };
  listeners.forEach((listener) => listener());
}

/** Snapshot of the module-level data status (mirrors the `X-OAP-Data-Stale` header). */
export function getDataStatus(): DataStatus {
  return status;
}

export function subscribeDataStatus(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Reset the status; used by tests. */
export function resetDataStatus(): void {
  setStale(false);
}

export function useDataStatus(): DataStatus {
  return useSyncExternalStore(subscribeDataStatus, getDataStatus, getDataStatus);
}

function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const seconds = Number(header);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

async function readError(response: Response): Promise<ApiError> {
  let detail = `${response.status} ${response.statusText}`.trim();
  let code: ErrorCode | null = null;
  try {
    const body = (await response.json()) as Partial<ErrorBody>;
    if (typeof body.detail === 'string') detail = body.detail;
    if (typeof body.code === 'string') code = body.code;
  } catch {
    // Body was not JSON (proxy error page, for example); keep the status line.
  }
  return new ApiError(
    response.status,
    detail,
    code,
    parseRetryAfter(response.headers.get('Retry-After')),
  );
}

/** GET `path` and parse JSON. Throws `ApiError` for non-2xx; tracks the stale header. */
export async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  if (!response.ok) throw await readError(response);
  setStale(response.headers.get('X-OAP-Data-Stale') === '1');
  return (await response.json()) as T;
}
