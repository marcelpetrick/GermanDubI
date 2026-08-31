/**
 * Interface translation.
 *
 * Deliberately dependency-free: four catalogues and a context are less code than the
 * configuration an i18n library would need at this size, and the catalogues are typed
 * against English so a missing key is a compile error rather than a blank in the UI.
 *
 * This translates the *interface* only. The dub is English to German whatever language the
 * buttons are in, which is why the language menu says so.
 */

import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';

import {
  CATALOGUES,
  initialLocale,
  interpolate,
  type Locale,
  LOCALE_STORAGE_KEY,
  type Translate,
} from './locales';

interface LocaleContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: Translate;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/** Provides the active interface language. */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // A choice that cannot be stored still applies for this session.
    }
  }, []);

  const value = useMemo<LocaleContextValue>(() => {
    const catalogue = CATALOGUES[locale];
    return {
      locale,
      setLocale,
      t: (key, values) => interpolate(catalogue[key], values),
    };
  }, [locale, setLocale]);

  return <LocaleContext value={value}>{children}</LocaleContext>;
}

/** Return the translator and the active locale. */
export function useLocale(): LocaleContextValue {
  const value = use(LocaleContext);
  if (!value) throw new Error('useLocale must be used inside a LocaleProvider.');
  return value;
}

/** Return just the translate function, which is what most components need. */
export function useT(): Translate {
  return useLocale().t;
}
