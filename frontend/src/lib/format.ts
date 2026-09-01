/** Formatting helpers shared by the segment table and the processing screen. */

import type { TranslationKey } from '@/i18n/en';
import { CATALOGUES, type Translate } from '@/i18n/locales';

/** Format milliseconds as `M:SS` or `H:MM:SS`, the way a video player does. */
export function formatTimestamp(milliseconds: number): string {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const mm = hours > 0 ? String(minutes).padStart(2, '0') : String(minutes);
  return hours > 0
    ? `${String(hours)}:${mm}:${String(seconds).padStart(2, '0')}`
    : `${mm}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Format a moment as wall-clock time in the reader's locale.
 *
 * The date is included only when it is not today: a dub started this morning wants
 * "09:14", and one started last Tuesday needs to say so.
 */
export function formatClock(iso: string, locale: string, now: Date = new Date()): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return '—';
  const sameDay = moment.toDateString() === now.toDateString();
  return moment.toLocaleString(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    ...(sameDay ? {} : { day: 'numeric', month: 'short' }),
  });
}

/** Return the milliseconds between two moments, or `null` when either is unusable. */
export function elapsedMs(from: string, to: string | Date): number | null {
  const start = new Date(from).getTime();
  const end = to instanceof Date ? to.getTime() : new Date(to).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;
  return end - start;
}

/** Format a duration in words, e.g. `12 min 30 s`. */
export function formatDuration(milliseconds: number): string {
  const total = Math.round(milliseconds / 1000);
  if (total < 60) return `${String(total)} s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return seconds === 0 ? `${String(minutes)} min` : `${String(minutes)} min ${String(seconds)} s`;
}

/**
 * Format a duration fit as a signed percentage.
 *
 * The sign matters more than the magnitude here: a reviewer is scanning for the segments
 * where the German runs long, so `+14%` must be visually distinct from `-3%`.
 */
export function formatDeviation(deviation: number): string {
  const percent = Math.round(deviation * 100);
  if (percent === 0) return '0%';
  return `${percent > 0 ? '+' : ''}${String(percent)}%`;
}

/** Format a byte count for the artifact list. */
export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit] ?? 'B'}`;
}

/**
 * Turn a snake_case flag into something readable, in the reader's language.
 *
 * A flag the catalogue does not know still has to render: a server newer than the browser
 * bundle can emit one, and `duration overrun` beats an empty badge.
 */
export function describeFlag(flag: string, t: Translate): string {
  const key = `flag.${flag}`;
  return key in CATALOGUES.en ? t(key as TranslationKey) : flag.replace(/_/g, ' ');
}
