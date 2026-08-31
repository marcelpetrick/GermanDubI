/**
 * Locale data and the helpers around it, kept apart from the provider component so that
 * editing a catalogue does not invalidate a component module during development.
 */

import { de } from './de';
import { type Catalogue, en, type TranslationKey } from './en';
import { hr } from './hr';
import { zh } from './zh';

export const LOCALES = ['en', 'de', 'hr', 'zh'] as const;
export type Locale = (typeof LOCALES)[number];

/** Names are written in their own language: a reader looking for theirs must recognise it. */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: 'English',
  de: 'Deutsch',
  hr: 'Hrvatski',
  zh: '\u4e2d\u6587',
};

export const CATALOGUES: Record<Locale, Catalogue> = { en, de, hr, zh };

export const LOCALE_STORAGE_KEY = 'germandubi.locale';

export type Translate = (key: TranslationKey, values?: Record<string, string | number>) => string;

function isLocale(value: unknown): value is Locale {
  return LOCALES.includes(value as Locale);
}

/** Choose a starting locale from storage, then the browser, then English. */
export function initialLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch {
    // Blocked site data is not a reason to fail; fall through to the browser's language.
  }
  for (const tag of window.navigator.languages ?? [window.navigator.language]) {
    const base = tag.split('-')[0]?.toLowerCase();
    if (isLocale(base)) return base;
  }
  return 'en';
}

/** Substitute `{name}` placeholders. Unknown names are left alone rather than blanked. */
export function interpolate(template: string, values?: Record<string, string | number>): string {
  if (!values) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in values ? String(values[name]) : match,
  );
}
