import '@testing-library/jest-dom/vitest';

/**
 * jsdom implements no media queries at all, so anything that asks the browser what the
 * user prefers throws rather than returning a default. The stub reports "not dark", which
 * is the same answer a browser with no preference gives.
 */
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
