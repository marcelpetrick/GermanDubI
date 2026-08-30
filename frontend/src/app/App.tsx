import { Link, Route, Routes } from 'react-router-dom';

import { HomePage } from '@/features/projects/HomePage';
import { useMeta } from '@/hooks/queries';

function ProjectPlaceholder() {
  return (
    <section className="card">
      <h1>Project</h1>
      <p className="muted">The project workspace is being connected.</p>
      <Link to="/">Back to projects</Link>
    </section>
  );
}

function NotFound() {
  return (
    <section className="card">
      <h1>Page not found</h1>
      <Link to="/">Back to projects</Link>
    </section>
  );
}

/** Top-level application layout and routes. */
export function App() {
  const meta = useMeta();

  return (
    <div className="app">
      <header className="topbar">
        <Link className="topbar__brand" to="/">
          GermanDubI
        </Link>
        <span className="topbar__tag">English video → editable German dub</span>
        <span className="topbar__spacer" />
        <span className="badge">Local workstation</span>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/projects/:projectId" element={<ProjectPlaceholder />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">
        {meta.data
          ? `GermanDubI ${meta.data.display_version} · API ${meta.data.api_version}`
          : 'GermanDubI'}
      </footer>
    </div>
  );
}
