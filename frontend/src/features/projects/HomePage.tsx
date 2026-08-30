import { type SyntheticEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { ErrorAlert } from '@/components/ErrorAlert';
import {
  useCreateAndAnalyzeProject,
  useDeleteProject,
  useHealth,
  useProjects,
} from '@/hooks/queries';
import { formatDuration } from '@/lib/format';

/** Landing page for starting and reopening dubbing projects. */
export function HomePage() {
  const [url, setUrl] = useState('');
  const navigate = useNavigate();
  const projects = useProjects();
  const health = useHealth();
  const create = useCreateAndAnalyzeProject();
  const remove = useDeleteProject();

  const submit = (event: SyntheticEvent<HTMLFormElement, SubmitEvent>) => {
    event.preventDefault();
    const source = url.trim();
    if (!source) return;
    create.mutate(source, {
      onSuccess: (project) => void navigate(`/projects/${project.id}`),
    });
  };

  const deleteProject = (id: string, title: string) => {
    if (window.confirm(`Delete “${title}” and all of its generated files?`)) remove.mutate(id);
  };

  return (
    <div className="stack">
      <section className="card card--hero">
        <h1>Turn an English video into a German dub</h1>
        <p className="muted">Paste a YouTube URL. Every segment stays editable and resumable.</p>
        <form className="source-form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="source-url">
            YouTube URL
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
            Analyze
          </button>
        </form>
        {create.error && <ErrorAlert error={create.error} />}
        {health.data?.status === 'degraded' && (
          <div className="alert alert--warn" role="status">
            Missing required tools: {health.data.missing.join(', ')}. Run <code>make doctor</code>.
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="recent-projects">
        <h2 id="recent-projects">Recent projects</h2>
        {projects.isPending && <p className="muted">Loading projects…</p>}
        {projects.error && <ErrorAlert error={projects.error} />}
        {projects.data?.length === 0 && <p className="muted">No projects yet.</p>}
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
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
