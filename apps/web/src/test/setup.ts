import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { resetDataStatus } from '../api/client';
import { requestLog, server } from './server';

// jsdom has no layout. This observer reports a fixed size as soon as an element is observed,
// so components sized by their container render at 800 x 600.
class ResizeObserverStub implements ResizeObserver {
  private readonly callback: ResizeObserverCallback;
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }
  observe(target: Element): void {
    const rect = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0 };
    this.callback(
      [{ target, contentRect: { ...rect, toJSON: () => rect } } as ResizeObserverEntry],
      this,
    );
  }
  unobserve(): void {}
  disconnect(): void {}
}
window.ResizeObserver = ResizeObserverStub;

window.matchMedia = (query: string): MediaQueryList =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;

(SVGElement.prototype as unknown as { getComputedTextLength: () => number }).getComputedTextLength =
  () => 0;

// Node's fetch needs absolute URLs (the app uses same-origin paths) and rejects jsdom's
// AbortSignal. The wrapper resolves paths and drops the signal; it goes on after server.listen()
// so it is the outermost layer, in front of MSW's interceptor.
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
  const intercepted = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const { signal: _signal, ...rest } = init ?? {};
    const target =
      typeof input === 'string' && input.startsWith('/')
        ? new URL(input, window.location.href).toString()
        : input;
    return intercepted(target, rest);
  };
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetDataStatus();
  requestLog.length = 0;
});
afterAll(() => server.close());
