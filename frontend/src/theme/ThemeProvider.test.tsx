import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { ThemeSwitcher } from '@/components/Switchers';
import { LocaleProvider } from '@/i18n/LocaleProvider';
import { ThemeProvider } from '@/theme/ThemeProvider';

function renderSwitcher() {
  return render(
    <ThemeProvider>
      <LocaleProvider>
        <ThemeSwitcher />
      </LocaleProvider>
    </ThemeProvider>,
  );
}

describe('theme', () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it('applies a concrete theme to the document rather than leaving it to CSS', () => {
    renderSwitcher();
    // The stylesheet has one definition per theme and no prefers-color-scheme fallback,
    // so an unset attribute would leave the page unstyled by either.
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('lets a reader override the system preference, and remembers it', async () => {
    const user = userEvent.setup();
    renderSwitcher();

    await user.click(screen.getByRole('button', { name: 'Dark' }));

    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem('germandubi.theme')).toBe('dark');
  });

  it('restores the stored preference on the next visit', () => {
    window.localStorage.setItem('germandubi.theme', 'dark');
    renderSwitcher();
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('ignores a stored value that is not a theme', () => {
    window.localStorage.setItem('germandubi.theme', 'chartreuse');
    renderSwitcher();
    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true');
  });
});
