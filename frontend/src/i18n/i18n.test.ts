import { describe, expect, it } from 'vitest';

import { CATALOGUES, interpolate, LOCALE_NAMES, LOCALES } from './locales';
import { en } from './en';

describe('catalogues', () => {
  const keys = Object.keys(en).sort();

  it.each(LOCALES)('%s defines exactly the English keys', (locale) => {
    // The type system already enforces this, but a catalogue is easy to edit carelessly
    // and a missing key renders as a blank in front of a reader rather than an error.
    expect(Object.keys(CATALOGUES[locale]).sort()).toEqual(keys);
  });

  it.each(LOCALES)('%s leaves no string empty', (locale) => {
    const blank = Object.entries(CATALOGUES[locale])
      .filter(([, value]) => value.trim() === '')
      .map(([key]) => key);
    expect(blank).toEqual([]);
  });

  it.each(LOCALES)('%s keeps every placeholder the English text uses', (locale) => {
    const placeholders = (value: string) => (value.match(/\{(\w+)\}/g) ?? []).sort();
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect(placeholders(CATALOGUES[locale][key]), key).toEqual(placeholders(en[key]));
    }
  });

  it('names every locale in its own language', () => {
    for (const locale of LOCALES) expect(LOCALE_NAMES[locale]).toBeTruthy();
  });
});

describe('interpolate', () => {
  it('substitutes named values', () => {
    expect(interpolate('Showing {shown} of {total}', { shown: 3, total: 9 })).toBe(
      'Showing 3 of 9',
    );
  });

  it('leaves an unknown placeholder alone rather than blanking it', () => {
    expect(interpolate('Hello {name}', { other: 'x' })).toBe('Hello {name}');
  });

  it('returns the template unchanged when there is nothing to substitute', () => {
    expect(interpolate('Plain text')).toBe('Plain text');
  });
});
