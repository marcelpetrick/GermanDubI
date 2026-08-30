import { describe, expect, it } from 'vitest';

import {
  describeFlag,
  formatBytes,
  formatDeviation,
  formatDuration,
  formatTimestamp,
} from './format';

describe('formatTimestamp', () => {
  it.each([
    [0, '0:00'],
    [1000, '0:01'],
    [61_000, '1:01'],
    [3_723_000, '1:02:03'],
  ])('formats %ims as %s', (ms, expected) => {
    expect(formatTimestamp(ms)).toBe(expected);
  });

  it('never renders a negative time', () => {
    expect(formatTimestamp(-500)).toBe('0:00');
  });
});

describe('formatDuration', () => {
  it.each([
    [5_000, '5 s'],
    [60_000, '1 min'],
    [90_000, '1 min 30 s'],
  ])('formats %ims as %s', (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });
});

describe('formatDeviation', () => {
  it('signs an overrun so it stands out while scanning', () => {
    expect(formatDeviation(0.14)).toBe('+14%');
  });

  it('signs an undershoot', () => {
    expect(formatDeviation(-0.03)).toBe('-3%');
  });

  it('shows an exact fit without a sign', () => {
    expect(formatDeviation(0)).toBe('0%');
  });
});

describe('formatBytes', () => {
  it.each([
    [null, '—'],
    [512, '512 B'],
    [2048, '2.0 KB'],
    [5_242_880, '5.0 MB'],
  ])('formats %s as %s', (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe('describeFlag', () => {
  it('translates a known flag into plain words', () => {
    expect(describeFlag('duration_overrun')).toBe('runs long');
  });

  it('falls back to the raw flag with underscores removed', () => {
    expect(describeFlag('some_new_flag')).toBe('some new flag');
  });
});
