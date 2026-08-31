/** Who made this, what it is built on, and under what terms. */

import { useT } from '@/i18n/LocaleProvider';
import { useMeta, useProviders } from '@/hooks/queries';

const REPOSITORY = 'https://github.com/marcelpetrick/GermanDubI';
const AUTHOR = 'Marcel Petrick';
const AUTHOR_EMAIL = 'mail@marcelpetrick.it';

/**
 * The third-party work this depends on, with the licence each is used under.
 *
 * Hand-maintained because a licence is a legal statement rather than runtime state: the
 * application cannot introspect it, and guessing would be worse than listing. What *is*
 * runtime state -- which providers are installed right now -- is read from the API instead.
 */
const TOOLS: readonly { name: string; role: string; licence: string; url: string }[] = [
  {
    name: 'FFmpeg',
    role: 'Audio and video processing',
    licence: 'LGPL-2.1-or-later / GPL-2.0-or-later',
    url: 'https://ffmpeg.org/',
  },
  {
    name: 'yt-dlp',
    role: 'Source acquisition',
    licence: 'Unlicense',
    url: 'https://github.com/yt-dlp/yt-dlp',
  },
  {
    name: 'faster-whisper',
    role: 'English speech recognition',
    licence: 'MIT',
    url: 'https://github.com/SYSTRAN/faster-whisper',
  },
  {
    name: 'Argos Translate',
    role: 'English to German translation',
    licence: 'MIT',
    url: 'https://github.com/argosopentech/argos-translate',
  },
  {
    name: 'Piper',
    role: 'German speech synthesis',
    licence: 'MIT',
    url: 'https://github.com/rhasspy/piper',
  },
  {
    name: 'Demucs',
    role: 'Voice and background separation',
    licence: 'MIT',
    url: 'https://github.com/adefossez/demucs',
  },
  {
    name: 'FastAPI',
    role: 'HTTP API',
    licence: 'MIT',
    url: 'https://fastapi.tiangolo.com/',
  },
  {
    name: 'React',
    role: 'Browser interface',
    licence: 'MIT',
    url: 'https://react.dev/',
  },
];

export function AboutPage() {
  const t = useT();
  const meta = useMeta();
  const providers = useProviders();

  return (
    <div className="stack">
      <section className="card card--hero">
        <h1>{t('about.title')}</h1>
        <p className="muted lede">{t('about.lede')}</p>
      </section>

      <section className="card" aria-labelledby="project">
        <h2 id="project">{t('about.projectTitle')}</h2>
        <dl className="facts">
          <div>
            <dt>{t('about.author')}</dt>
            <dd>
              {AUTHOR} · <a href={`mailto:${AUTHOR_EMAIL}`}>{AUTHOR_EMAIL}</a>
            </dd>
          </div>
          <div>
            <dt>{t('about.license')}</dt>
            <dd>{t('about.licenseBody')}</dd>
          </div>
          <div>
            <dt>{t('about.repository')}</dt>
            <dd>
              <a href={REPOSITORY} target="_blank" rel="noreferrer noopener">
                {REPOSITORY}
              </a>
            </dd>
          </div>
        </dl>
      </section>

      <section className="card" aria-labelledby="build">
        <h2 id="build">{t('about.buildTitle')}</h2>
        <dl className="facts">
          <div>
            <dt>{t('about.version')}</dt>
            <dd className="mono">{meta.data?.display_version ?? '—'}</dd>
          </div>
          <div>
            <dt>{t('about.apiVersion')}</dt>
            <dd className="mono">{meta.data?.api_version ?? '—'}</dd>
          </div>
          <div>
            <dt>{t('about.revision')}</dt>
            <dd className="mono">{meta.data?.git_revision ?? '—'}</dd>
          </div>
          <div>
            <dt>{t('about.languages')}</dt>
            <dd className="mono">
              {meta.data ? `${meta.data.source_language} → ${meta.data.target_language}` : '—'}
            </dd>
          </div>
        </dl>
      </section>

      <section className="card" aria-labelledby="providers">
        <h2 id="providers">{t('about.providersTitle')}</h2>
        <p className="muted">{t('about.providersLede')}</p>
        <dl className="facts">
          {providers.data?.map((provider) => (
            <div key={provider.id}>
              <dt>{provider.name}</dt>
              <dd className="row">
                <span className={`badge badge--${provider.kind === 'network' ? 'warn' : 'ok'}`}>
                  {provider.kind === 'network'
                    ? t('about.providerNetwork')
                    : t('about.providerLocal')}
                </span>
                <span className="muted small">
                  {provider.available ? t('about.providerReady') : t('about.providerMissing')}
                </span>
                {provider.notes && <span className="muted small">{provider.notes}</span>}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card" aria-labelledby="tools">
        <h2 id="tools">{t('about.toolsTitle')}</h2>
        <p className="muted">{t('about.toolsLede')}</p>
        <dl className="facts">
          {TOOLS.map((tool) => (
            <div key={tool.name}>
              <dt>
                <a href={tool.url} target="_blank" rel="noreferrer noopener">
                  {tool.name}
                </a>
              </dt>
              <dd>
                {tool.role} · <span className="muted">{tool.licence}</span>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card prose" aria-labelledby="rights">
        <h2 id="rights">{t('about.rightsTitle')}</h2>
        <p>{t('about.rightsBody')}</p>
      </section>
    </div>
  );
}
