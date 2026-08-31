import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { LanguageSwitcher } from '@/components/Switchers';
import { LocaleProvider, useT } from '@/i18n/LocaleProvider';
import { ThemeProvider } from '@/theme/ThemeProvider';

function Probe() {
  const t = useT();
  return <p>{t('nav.about')}</p>;
}

function renderSwitcher() {
  return render(
    <ThemeProvider>
      <LocaleProvider>
        <LanguageSwitcher />
        <Probe />
      </LocaleProvider>
    </ThemeProvider>,
  );
}

describe('interface language', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts in English when nothing else is known', () => {
    renderSwitcher();
    expect(screen.getByText('About')).toBeInTheDocument();
  });

  it('switches the interface and remembers the choice', async () => {
    const user = userEvent.setup();
    renderSwitcher();

    await user.selectOptions(screen.getByRole('combobox'), 'de');

    expect(screen.getByText('Über')).toBeInTheDocument();
    expect(window.localStorage.getItem('germandubi.locale')).toBe('de');
    // Assistive technology and hyphenation both depend on this being right.
    expect(document.documentElement.lang).toBe('de');
  });

  it('restores a stored language', () => {
    window.localStorage.setItem('germandubi.locale', 'hr');
    renderSwitcher();
    expect(screen.getByText('O programu')).toBeInTheDocument();
  });

  it('says that the choice does not change the dub', () => {
    renderSwitcher();
    expect(screen.getByRole('combobox')).toHaveAttribute(
      'title',
      expect.stringContaining('English to German'),
    );
  });
});
