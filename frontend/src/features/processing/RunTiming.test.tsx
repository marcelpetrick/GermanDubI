import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Run } from '@/api/types';
import { RunTiming } from '@/features/processing/RunTiming';
import { LocaleProvider } from '@/i18n/LocaleProvider';
import { LOCALE_STORAGE_KEY } from '@/i18n/locales';

const STARTED = '2026-09-01T15:51:35.000Z';

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: '01KRUN0000000000000000000',
    project_id: '01KPROJECT000000000000000',
    stages: ['assemble'],
    jobs: [],
    progress: 0.5,
    finished: false,
    failed: false,
    cancelled: false,
    current_stage: 'assemble',
    created_at: STARTED,
    finished_at: null,
    queue_position: null,
    queue_length: 0,
    ...overrides,
  };
}

function show(value: Run, locale = 'en') {
  window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  return render(
    <LocaleProvider>
      <RunTiming run={value} />
    </LocaleProvider>,
  );
}

describe('RunTiming', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-01T16:09:42.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('counts up while the run is still going', () => {
    show(run());

    // 15:51:35 to 16:09:42 is 18 minutes and 7 seconds.
    expect(screen.getByRole('time')).toHaveTextContent('running for 18 min 7 s');
    expect(screen.getByRole('time')).not.toHaveTextContent('finished');
  });

  it('reports how long a finished run took', () => {
    show(run({ finished: true, finished_at: '2026-09-01T16:09:42.000Z', progress: 1 }));

    const line = screen.getByRole('time');
    expect(line).toHaveTextContent('Started');
    expect(line).toHaveTextContent('finished');
    expect(line).toHaveTextContent('took 18 min 7 s');
  });

  it('advances a live run without a refetch', () => {
    show(run());
    expect(screen.getByRole('time')).toHaveTextContent('18 min 7 s');

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(screen.getByRole('time')).toHaveTextContent('18 min 10 s');
  });

  it('translates the labels', () => {
    show(run({ finished: true, finished_at: '2026-09-01T16:09:42.000Z' }), 'de');

    expect(screen.getByRole('time')).toHaveTextContent('Gestartet');
    expect(screen.getByRole('time')).toHaveTextContent('Dauer 18 min 7 s');
  });

  it('survives a run whose timestamps make no sense', () => {
    show(run({ created_at: 'not a date', finished_at: 'also not a date' }));

    // A broken timestamp must not blank the page or render "NaN".
    expect(screen.getByRole('time')).toHaveTextContent('—');
    expect(screen.getByRole('time')).not.toHaveTextContent('NaN');
  });
});
