import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

function Explodes(): never {
  throw new Error('render blew up');
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // React logs the caught error itself; silencing keeps the run readable.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('shows what is fine as well as what is not, instead of a blank page', () => {
    render(
      <ErrorBoundary>
        <Explodes />
      </ErrorBoundary>,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/stopped working/i)).toBeInTheDocument();
    // A reader's first question is whether their work survived.
    expect(screen.getByText(/projects and files are untouched/i)).toBeInTheDocument();
    expect(screen.getByText('render blew up')).toBeInTheDocument();
  });

  it('offers a reload, because that is the one action that can help', async () => {
    const reload = vi.fn();
    const original = window.location;
    // jsdom's `reload` is not configurable, so the whole object is swapped and put back.
    const stub: Location = Object.create(Location.prototype) as Location;
    Object.defineProperty(stub, 'reload', { configurable: true, value: reload });
    Object.defineProperty(window, 'location', { configurable: true, value: stub });

    try {
      render(
        <ErrorBoundary>
          <Explodes />
        </ErrorBoundary>,
      );
      await userEvent.click(screen.getByRole('button', { name: /reload/i }));
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original });
    }

    expect(reload).toHaveBeenCalledOnce();
  });

  it('renders its children untouched when nothing throws', () => {
    render(
      <ErrorBoundary>
        <p>the actual application</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText('the actual application')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
