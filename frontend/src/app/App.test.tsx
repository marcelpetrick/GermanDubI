import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { api } from '@/api/client';
import type { Health, Meta, ProjectDetail } from '@/api/types';
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

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

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
  vi.spyOn(api, 'listProjects').mockResolvedValue([]);
  const create = vi.spyOn(api, 'createProject').mockResolvedValue(project);
  const analyze = vi.spyOn(api, 'analyzeProject').mockResolvedValue({} as never);

  renderApp();
  await user.type(
    screen.getByLabelText('YouTube URL'),
    'https://www.youtube.com/watch?v=abcdefghijk',
  );
  await user.click(screen.getByRole('button', { name: 'Analyze' }));

  expect(create).toHaveBeenCalledWith('https://www.youtube.com/watch?v=abcdefghijk');
  expect(analyze).toHaveBeenCalledWith(project.id);
  expect(await screen.findByRole('heading', { name: 'Project' })).toBeInTheDocument();
});
