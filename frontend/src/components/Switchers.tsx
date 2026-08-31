/** Theme and interface-language controls, small enough to live in the header. */

import { useLocale, useT } from '@/i18n/LocaleProvider';
import { LOCALE_NAMES, LOCALES, type Locale } from '@/i18n/locales';
import { THEME_PREFERENCES, useTheme } from '@/theme/ThemeProvider';

/** Light / dark / follow-the-system, as a three-way toggle. */
export function ThemeSwitcher() {
  const t = useT();
  const { preference, setPreference } = useTheme();

  return (
    <div className="switcher" role="group" aria-label={t('theme.label')}>
      {THEME_PREFERENCES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={preference === option}
          onClick={() => {
            setPreference(option);
          }}
        >
          {t(`theme.${option}`)}
        </button>
      ))}
    </div>
  );
}

/**
 * Interface language.
 *
 * A select rather than a row of buttons: four options is already too wide for a header, and
 * a select carries its own accessible name and keyboard behaviour.
 */
export function LanguageSwitcher() {
  const t = useT();
  const { locale, setLocale } = useLocale();

  return (
    <select
      className="select-inline"
      aria-label={t('language.label')}
      title={t('language.note')}
      value={locale}
      onChange={(event) => {
        setLocale(event.target.value as Locale);
      }}
    >
      {LOCALES.map((option) => (
        <option key={option} value={option}>
          {LOCALE_NAMES[option]}
        </option>
      ))}
    </select>
  );
}
