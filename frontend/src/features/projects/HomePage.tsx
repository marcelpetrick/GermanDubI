import { type SyntheticEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { ErrorAlert } from '@/components/ErrorAlert';
import {
  useCreateAndAnalyzeProject,
  useDeleteProject,
  useHealth,
  useProjects,
} from '@/hooks/queries';
import { VoicePicker } from '@/features/projects/VoicePicker';
import { useT } from '@/i18n/LocaleProvider';
import { formatDuration } from '@/lib/format';

/** Landing page for starting and reopening dubbing projects. */
export function HomePage() {
  const t = useT();
  const [url, setUrl] = useState('');
  const [voice, setVoice] = useState<string | null>(null);
  const navigate = useNavigate();
  const projects = useProjects();
  const health = useHealth();
  const create = useCreateAndAnalyzeProject();
  const remove = useDeleteProject();

  const submit = (event: SyntheticEvent<HTMLFormElement, SubmitEvent>) => {
    event.preventDefault();
    const source = url.trim();
    if (!source) return;
    create.mutate(
      { url: source, voice },
      { onSuccess: (project) => void navigate(`/projects/${project.id}`) },
    );
  };

  const deleteProject = (id: string, title: string) => {
    if (window.confirm(t('home.confirmDelete', { title }))) remove.mutate(id);
  };

  return (
    <div className="stack">
      <section className="card card--hero">
        <h1>{t('home.title')}</h1>
        <p className="muted lede">{t('home.subtitle')}</p>
        <form className="source-form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="source-url">
            {t('home.urlLabel')}
          </label>
          <input
            id="source-url"
            type="url"
            required
            placeholder="https://www.youtube.com/watch?v=…"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
            }}
          />
          <button className="primary" type="submit" disabled={create.isPending}>
            {create.isPending && <span className="spinner" aria-hidden="true" />}
            {t('home.analyze')}
          </button>
        </form>
        <VoicePicker value={voice} onChange={setVoice} />
        {create.error && <ErrorAlert error={create.error} />}
        {health.data?.status === 'degraded' && (
          <div className="alert alert--warn" role="status">
            {t('home.degraded')} {t('home.degradedHelp', { command: 'germandubi doctor' })}
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="recent-projects">
        <h2 id="recent-projects">{t('home.recent')}</h2>
        {projects.isPending && <p className="muted">{t('home.loading')}</p>}
        {projects.error && <ErrorAlert error={projects.error} />}
        {projects.data?.length === 0 && (
          <div className="empty">
            <p>
              <strong>{t('home.emptyTitle')}</strong>
            </p>
            <p>{t('home.emptyBody')}</p>
            <p>
              <Link to="/help">{t('home.newToThis')}</Link>
            </p>
          </div>
        )}
        {projects.data && projects.data.length > 0 && (
          <ul className="project-list">
            {projects.data.map((project) => (
              <li className="project-list__item" key={project.id}>
                <Link className="project-list__title" to={`/projects/${project.id}`}>
                  {project.title}
                </Link>
                {project.duration_ms !== null && (
                  <span className="muted small">{formatDuration(project.duration_ms)}</span>
                )}
                <span className={`badge badge--${project.state === 'failed' ? 'danger' : 'ok'}`}>
                  {project.state}
                </span>
                <button
                  className="link danger"
                  type="button"
                  disabled={remove.isPending}
                  onClick={() => {
                    deleteProject(project.id, project.title);
                  }}
                >
                  {t('home.delete')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
