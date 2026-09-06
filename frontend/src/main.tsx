import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from '@/app/App';
import { ErrorBoundary } from '@/app/ErrorBoundary';
import { LocaleProvider } from '@/i18n/LocaleProvider';
import { ThemeProvider } from '@/theme/ThemeProvider';
import '@/styles/index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

const root = document.querySelector<HTMLElement>('#root');
if (!root) throw new Error('The application root element is missing.');

createRoot(root).render(
  <StrictMode>
    {/* Outermost, so a failure in any provider below still reaches a page rather than a
        blank document. */}
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <LocaleProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </LocaleProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
