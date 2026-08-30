import { Link, Route, Routes } from 'react-router-dom';

import { HomePage } from '@/features/projects/HomePage';
import { ProjectPage } from '@/features/projects/ProjectPage';
import { useMeta } from '@/hooks/queries';

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
          <Route path="/projects/:projectId" element={<ProjectPage />} />
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
