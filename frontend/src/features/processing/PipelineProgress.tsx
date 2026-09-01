import type { Job, Run } from '@/api/types';
import { CATALOGUES } from '@/i18n/locales';
import type { TranslationKey } from '@/i18n/en';
import { useT } from '@/i18n/LocaleProvider';

/** Persisted pipeline progress, optionally enriched by the latest live event detail. */
export function PipelineProgress({ run, liveDetail }: { run: Run; liveDetail: string | null }) {
  const t = useT();
  const percent = Math.round(run.progress * 100);
  // One worker processes one project at a time, so a second video is accepted straight away
  // and then waits its turn. Unannounced, a bar at zero with no running stage is
  // indistinguishable from a hang.
  const position = run.queue_position ?? null;
  return (
    <section className="card" aria-labelledby="processing-heading" aria-live="polite">
      <div className="row section-heading">
        <div>
          <h2 id="processing-heading">{t('processing.title')}</h2>
          <p className="muted small">
            {liveDetail ?? t('processing.percentComplete', { percent })}
          </p>
        </div>
        <strong>{percent}%</strong>
      </div>
      {position !== null && (
        <p className="alert alert--warn" role="status">
          {position === 1 ? t('queue.next') : t('queue.waiting')}
          {run.queue_length > 1 &&
            ` · ${t('queue.position', { position, total: run.queue_length })}`}
        </p>
      )}
      <div
        className="progress"
        role="progressbar"
        aria-label={t('processing.progressLabel')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <div className="progress__bar" style={{ width: `${String(percent)}%` }} />
      </div>
      <ol className="stages">
        {run.jobs.map((job) => (
          <StageRow key={job.stage} job={job} />
        ))}
      </ol>
    </section>
  );
}

/**
 * Look a key up only when the catalogue has it.
 *
 * Stage identifiers and job statuses come from the server, so an older browser bundle meeting
 * a newer server would otherwise render the raw key. Falling back to the server's own English
 * text is worse than a translation and better than `stage.deflicker`.
 */
function known(key: string): TranslationKey | null {
  return key in CATALOGUES.en ? (key as TranslationKey) : null;
}

function StageRow({ job }: { job: Job }) {
  const t = useT();
  const running = job.status === 'running';
  const mark =
    job.status === 'succeeded' ? '✓' : job.status === 'failed' ? '!' : running ? '●' : '·';
  const stageKey = known(`stage.${job.stage}`);
  const statusKey = known(`jobStatus.${job.status}`);
  return (
    <li className={`stage${running ? ' stage--running' : ''}`}>
      <span className="stage__mark" aria-hidden="true">
        {mark}
      </span>
      <span>{stageKey ? t(stageKey) : job.label}</span>
      <span className="stage__detail">
        {job.error ?? job.detail ?? (statusKey ? t(statusKey) : job.status)}
      </span>
    </li>
  );
}
