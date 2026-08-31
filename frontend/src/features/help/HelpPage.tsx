/** What the pipeline does, for someone who has just opened the app. */

import { Link } from 'react-router-dom';

import type { Stage } from '@/api/types';
import type { TranslationKey } from '@/i18n/en';
import { useT } from '@/i18n/LocaleProvider';

/**
 * Every stage, in execution order, with the key that explains it.
 *
 * Typed as `Record<Stage, TranslationKey>` where `Stage` comes from the generated OpenAPI
 * schema. Adding or removing a pipeline stage therefore fails the build here rather than
 * quietly leaving this page describing a product that no longer exists.
 */
const STAGE_EXPLANATIONS: Record<Stage, TranslationKey> = {
  probe: 'help.stage.probe',
  acquire: 'help.stage.acquire',
  normalize: 'help.stage.normalize',
  transcribe: 'help.stage.transcribe',
  align: 'help.stage.align',
  segment: 'help.stage.segment',
  separate: 'help.stage.separate',
  translate: 'help.stage.translate',
  prosody: 'help.stage.prosody',
  synthesize: 'help.stage.synthesize',
  fit: 'help.stage.fit',
  assemble: 'help.stage.assemble',
  mix: 'help.stage.mix',
  subtitle: 'help.stage.subtitle',
  qa: 'help.stage.qa',
  export: 'help.stage.export',
};

/** Insertion order is execution order, which the record's type cannot express. */
const STAGES = Object.entries(STAGE_EXPLANATIONS);

const STEPS: readonly { title: TranslationKey; body: TranslationKey }[] = [
  { title: 'help.step1Title', body: 'help.step1Body' },
  { title: 'help.step2Title', body: 'help.step2Body' },
  { title: 'help.step3Title', body: 'help.step3Body' },
  { title: 'help.step4Title', body: 'help.step4Body' },
  { title: 'help.step5Title', body: 'help.step5Body' },
];

export function HelpPage() {
  const t = useT();

  return (
    <div className="stack">
      <section className="card card--hero">
        <h1>{t('help.title')}</h1>
        <p className="muted lede">{t('help.lede')}</p>
      </section>

      <section className="card" aria-labelledby="walkthrough">
        <h2 id="walkthrough">{t('help.walkthroughTitle')}</h2>
        <ol className="steps">
          {STEPS.map((step, index) => (
            <li className="step" key={step.title}>
              <span className="step__index" aria-hidden="true">
                {index + 1}
              </span>
              <div>
                <h3 className="step__title">{t(step.title)}</h3>
                <p className="step__body">{t(step.body)}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="card" aria-labelledby="stages">
        <h2 id="stages">{t('help.stagesTitle')}</h2>
        <p className="muted">{t('help.stagesLede')}</p>
        <ol className="stage-grid">
          {STAGES.map(([stage, explanation], index) => (
            <li className="stage-card" key={stage}>
              <div className="stage-card__name">
                <span className="muted mono small">{String(index + 1).padStart(2, '0')}</span>{' '}
                {stage}
              </div>
              <p className="stage-card__what">{t(explanation)}</p>
            </li>
          ))}
        </ol>
      </section>

      <div className="split-even">
        <section className="card prose" aria-labelledby="editing">
          <h2 id="editing">{t('help.editTitle')}</h2>
          <p>{t('help.editBody')}</p>
        </section>
        <section className="card prose" aria-labelledby="timing">
          <h2 id="timing">{t('help.timingTitle')}</h2>
          <p>{t('help.timingBody')}</p>
        </section>
      </div>

      <section className="card prose" aria-labelledby="privacy">
        <h2 id="privacy">{t('help.privacyTitle')}</h2>
        <p>{t('help.privacyBody')}</p>
        <p>
          <Link to="/about">{t('nav.about')}</Link>
        </p>
      </section>
    </div>
  );
}
