import { Link, NavLink, Route, Routes } from 'react-router-dom';

import { LanguageSwitcher, ThemeSwitcher } from '@/components/Switchers';
import { AboutPage } from '@/features/about/AboutPage';
import { HelpPage } from '@/features/help/HelpPage';
import { HomePage } from '@/features/projects/HomePage';
import { ProjectPage } from '@/features/projects/ProjectPage';
import { useMeta } from '@/hooks/queries';
import { useT } from '@/i18n/LocaleProvider';

function NotFound() {
  const t = useT();
  return (
    <section className="card">
      <h1>{t('notFound.title')}</h1>
      <Link to="/">{t('notFound.back')}</Link>
    </section>
  );
}

/** Top-level application layout and routes. */
export function App() {
  const t = useT();
  const meta = useMeta();
  const version = meta.data?.display_version;

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        {t('app.skipToContent')}
      </a>
      <header className="topbar">
        <Link className="topbar__brand" to="/">
          GermanDubI
        </Link>
        <span className="topbar__tag">{t('app.tagline')}</span>
        <span className="topbar__spacer" />
        <nav className="topbar__nav" aria-label={t('nav.projects')}>
          <NavLink className="topbar__link" to="/" end>
            {t('nav.projects')}
          </NavLink>
          <NavLink className="topbar__link" to="/help">
            {t('nav.help')}
          </NavLink>
          <NavLink className="topbar__link" to="/about">
            {t('nav.about')}
          </NavLink>
        </nav>
        <LanguageSwitcher />
        <ThemeSwitcher />
        {/* The running version, always visible and always a route to what it means. */}
        <Link className="version-chip" to="/about" title={t('about.version')}>
          {version ?? '…'}
        </Link>
      </header>
      <main className="main" id="main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">
        <span>
          {meta.data
            ? `GermanDubI ${meta.data.display_version} · API ${meta.data.api_version}`
            : 'GermanDubI'}
        </span>
        <span className="footer__spacer" />
        <span>{t('app.localBadge')}</span>
      </footer>
    </div>
  );
}
