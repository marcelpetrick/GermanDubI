import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Run } from '@/api/types';
import { PipelineProgress } from '@/features/processing/PipelineProgress';
import { LocaleProvider } from '@/i18n/LocaleProvider';
import { LOCALE_STORAGE_KEY } from '@/i18n/locales';

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: '01KRUN0000000000000000000',
    project_id: '01KPROJECT000000000000000',
    stages: ['acquire', 'normalize'],
    jobs: [
      {
        stage: 'acquire',
        label: 'Downloading media',
        status: 'queued',
        progress: 0,
        detail: null,
        attempt: 0,
        error: null,
      },
    ],
    progress: 0,
    finished: false,
    failed: false,
    cancelled: false,
    current_stage: null,
    created_at: '2026-08-30T12:00:00Z',
    queue_position: null,
    queue_length: 0,
    ...overrides,
  };
}

function show(value: Run, locale = 'en') {
  window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  return render(
    <LocaleProvider>
      <PipelineProgress run={value} liveDetail={null} />
    </LocaleProvider>,
  );
}

describe('PipelineProgress', () => {
  it('says nothing about a queue when nothing is waiting', () => {
    show(run());

    expect(screen.queryByRole('status')).toBeNull();
  });

  it('explains a wait behind another project', () => {
    show(run({ queue_position: 2, queue_length: 3 }));

    // A bar at zero with no running stage is otherwise indistinguishable from a hang.
    expect(screen.getByRole('status')).toHaveTextContent('Waiting for another project to finish');
    expect(screen.getByRole('status')).toHaveTextContent('Position 2 of 3 in the queue');
  });

  it('says a project is next rather than counting a queue of one', () => {
    show(run({ queue_position: 1, queue_length: 1 }));

    expect(screen.getByRole('status')).toHaveTextContent('Next in the queue');
    expect(screen.getByRole('status')).not.toHaveTextContent('Position');
  });

  it('translates the stage names the server identifies', () => {
    show(run(), 'de');

    // The server sends an English label as well; the identifier is what is translated.
    expect(screen.getByText('Medien werden geladen')).toBeInTheDocument();
  });
});
