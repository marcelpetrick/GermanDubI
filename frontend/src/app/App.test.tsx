import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { LocaleProvider } from '@/i18n/LocaleProvider';
import { ThemeProvider } from '@/theme/ThemeProvider';

import { api } from '@/api/client';
import type { Health, Meta, ProjectDetail, Run, Segment } from '@/api/types';
import { App } from '@/app/App';

const meta: Meta = {
  application: 'germandubi',
  version: '0.1.0',
  display_version: '0.1.0',
  api_version: 'v1',
  git_revision: null,
  dirty: false,
  source_language: 'en',
  target_language: 'de',
};

const health: Health = { status: 'ok', tools: {}, missing: [], data_dir: '/tmp', writable: true };

function renderApp(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <LocaleProvider>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </LocaleProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('creates and analyzes a project from the primary action', async () => {
  const user = userEvent.setup();
  const project = {
    id: '01KTESTPROJECT000000000000',
    title: 'New project',
    state: 'new',
    source_kind: 'youtube',
    source_locator: 'https://www.youtube.com/watch?v=abcdefghijk',
    duration_ms: null,
    thumbnail_url: null,
    created_at: '2026-08-30T12:00:00Z',
    updated_at: '2026-08-30T12:00:00Z',
    source_language: 'en',
    target_language: 'de',
    quality: 'balanced',
    error: null,
    media: null,
  } satisfies ProjectDetail;

  vi.spyOn(api, 'meta').mockResolvedValue(meta);
  vi.spyOn(api, 'health').mockResolvedValue(health);
  vi.spyOn(api, 'voices').mockResolvedValue([]);
  vi.spyOn(api, 'listProjects').mockResolvedValue([]);
  const create = vi.spyOn(api, 'createProject').mockResolvedValue(project);
  const analyze = vi.spyOn(api, 'analyzeProject').mockResolvedValue({} as never);
  vi.spyOn(api, 'getProject').mockResolvedValue(project);
  vi.spyOn(api, 'latestRun').mockResolvedValue(null);

  renderApp();
  await user.type(
    screen.getByLabelText('YouTube URL'),
    'https://www.youtube.com/watch?v=abcdefghijk',
  );
  await user.click(screen.getByRole('button', { name: 'Analyze' }));

  expect(create).toHaveBeenCalledWith('https://www.youtube.com/watch?v=abcdefghijk', null);
  expect(analyze).toHaveBeenCalledWith(project.id);
  expect(await screen.findByRole('heading', { name: 'New project' })).toBeInTheDocument();
});

test('starts the full dub from an analyzed project', async () => {
  const user = userEvent.setup();
  const project = projectInState('ready');
  const run = runFor(project.id);
  vi.spyOn(api, 'meta').mockResolvedValue(meta);
  vi.spyOn(api, 'getProject').mockResolvedValue(project);
  vi.spyOn(api, 'latestRun').mockResolvedValue(null);
  const start = vi.spyOn(api, 'startRun').mockResolvedValue(run);

  renderApp(`/projects/${project.id}`);
  await user.click(await screen.findByRole('button', { name: 'Create German dub' }));

  expect(start).toHaveBeenCalledWith(project.id);
});

test('saves a German correction and requests minimal regeneration', async () => {
  const user = userEvent.setup();
  const project = projectInState('complete');
  const segment = segmentFixture();
  vi.spyOn(api, 'meta').mockResolvedValue(meta);
  vi.spyOn(api, 'getProject').mockResolvedValue(project);
  vi.spyOn(api, 'latestRun').mockResolvedValue(null);
  vi.spyOn(api, 'listArtifacts').mockResolvedValue([]);
  vi.spyOn(api, 'listSegments').mockResolvedValue({
    segments: [segment],
    summary: { total: 1, translated: 1, synthesized: 1, approved: 0, flagged: 0, failed: 0 },
  });
  const update = vi.spyOn(api, 'updateSegment').mockResolvedValue({
    segment: { ...segment, translation: 'Korrigierter Satz', translation_origin: 'human' },
    invalidated_from: 'synthesize',
    run_id: '01KREGEN00000000000000000',
  });

  renderApp(`/projects/${project.id}`);
  const editor = await screen.findByLabelText('German translation');
  await user.clear(editor);
  await user.type(editor, 'Korrigierter Satz');
  await user.click(screen.getByRole('button', { name: 'Save German & regenerate' }));

  expect(update).toHaveBeenCalledWith(
    project.id,
    segment.id,
    { translation: 'Korrigierter Satz' },
    true,
  );
});

function projectInState(state: string): ProjectDetail {
  return {
    id: '01KTESTPROJECT000000000000',
    title: 'Timing explained',
    state,
    source_kind: 'youtube',
    source_locator: 'https://www.youtube.com/watch?v=abcdefghijk',
    duration_ms: 15_000,
    thumbnail_url: null,
    created_at: '2026-08-30T12:00:00Z',
    updated_at: '2026-08-30T12:00:00Z',
    source_language: 'en',
    target_language: 'de',
    quality: 'balanced',
    error: null,
    media: {
      title: 'Timing explained',
      duration_ms: 15_000,
      has_english_captions: true,
      best_captions_are_automatic: false,
      captions: [],
    },
  };
}

function runFor(projectId: string, overrides: Partial<Run> = {}): Run {
  return {
    id: '01KRUN0000000000000000000',
    project_id: projectId,
    stages: ['acquire'],
    jobs: [],
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

function segmentFixture(): Segment {
  return {
    id: '01KSEGMENT0000000000000000',
    ordinal: 0,
    start_ms: 0,
    end_ms: 2500,
    duration_ms: 2500,
    source_text: 'Timing is important.',
    source_origin: 'captions',
    translation: 'Timing ist wichtig.',
    translation_origin: 'machine',
    status: 'fitted',
    review_state: 'unreviewed',
    flags: [],
    confidence: 0.98,
    fit: { target_ms: 2500, generated_ms: 2600, ratio: 1.04, deviation: 0.04, applied_rate: 1 },
    has_speech: true,
    word_count: 3,
  };
}
