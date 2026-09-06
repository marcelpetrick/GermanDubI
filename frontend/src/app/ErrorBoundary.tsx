/**
 * The last thing between a render error and a white page.
 *
 * React unmounts the whole tree when a render throws, so without a boundary the reader
 * gets a blank document and the explanation goes to a console they will never open. That
 * is indistinguishable from the server being down, and it is the one failure they cannot
 * report usefully.
 *
 * It reads the catalogue directly rather than through `useLocale`, deliberately: a
 * boundary that needed a context could not report a failure in the provider that supplies
 * it, which is exactly when a page goes blank after a bad deploy. That costs it live
 * language switching, which a crash screen does not need.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';

import { CATALOGUES, initialLocale } from '@/i18n/locales';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Still logged: the reader gets the summary, whoever they report it to gets the stack.
    console.error('The interface failed to render.', error, info.componentStack);
  }

  private readonly reload = () => {
    window.location.reload();
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    const t = CATALOGUES[initialLocale()];
    return (
      <div className="error-boundary" role="alert">
        <h1>{t['boundary.title']}</h1>
        <p>{t['boundary.body']}</p>
        {/* The message, not the stack: it is what identifies the fault in a report, and
            the stack is in the console for anyone who can use it. */}
        <pre className="error-boundary__detail">{error.message}</pre>
        <button type="button" className="button" onClick={this.reload}>
          {t['boundary.reload']}
        </button>
        <p className="error-boundary__hint">{t['boundary.hint']}</p>
      </div>
    );
  }
}
