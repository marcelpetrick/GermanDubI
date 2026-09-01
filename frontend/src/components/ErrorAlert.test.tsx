import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApiError } from '@/api/client';
import { ErrorAlert } from '@/components/ErrorAlert';
import { LocaleProvider } from '@/i18n/LocaleProvider';
import { LOCALE_STORAGE_KEY } from '@/i18n/locales';

function show(error: unknown, locale?: string) {
  if (locale) window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  else window.localStorage.removeItem(LOCALE_STORAGE_KEY);
  return render(
    <LocaleProvider>
      <ErrorAlert error={error} />
    </LocaleProvider>,
  );
}

describe('ErrorAlert', () => {
  it('translates the heading from the error code', () => {
    show(
      new ApiError(503, {
        code: 'provider_unavailable',
        message: 'No German voice is installed.',
        details: {},
      }),
      'de',
    );

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Eine benötigte Komponente ist nicht installiert',
    );
    // The server's own sentence is kept: it is the specific diagnostic, and mirroring the
    // backend's whole message catalogue in the browser would drift within a release.
    expect(screen.getByRole('alert')).toHaveTextContent('No German voice is installed.');
  });

  it('falls back to the generic heading for a code it has never seen', () => {
    show(
      new ApiError(500, { code: 'a_code_from_a_newer_server', message: 'Broken.', details: {} }),
      'en',
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
  });

  it('shows the reference and where the log is', () => {
    show(
      new ApiError(500, {
        code: 'internal_error',
        message: 'Something went wrong. The server log has the details.',
        details: { reference: 'a1b2c3d4', log_file: '/home/me/.local/share/germandubi/logs/x.log' },
      }),
      'en',
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Reference a1b2c3d4');
    // "Check the server log" without naming the log is not an instruction.
    expect(alert).toHaveTextContent('/home/me/.local/share/germandubi/logs/x.log');
  });

  it('points at the terminal when the server logs to no file', () => {
    show(
      new ApiError(500, {
        code: 'internal_error',
        message: 'Something went wrong. The server log has the details.',
        details: { reference: 'a1b2c3d4' },
      }),
      'en',
    );

    expect(screen.getByRole('alert')).toHaveTextContent('the terminal running the server');
  });

  it('handles an error that never reached the server', () => {
    show(new Error('Failed to fetch'), 'en');

    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to fetch');
  });
});
