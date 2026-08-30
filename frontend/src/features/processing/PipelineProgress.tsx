import type { Job, Run } from '@/api/types';

/** Persisted pipeline progress, optionally enriched by the latest live event detail. */
export function PipelineProgress({ run, liveDetail }: { run: Run; liveDetail: string | null }) {
  const percent = Math.round(run.progress * 100);
  return (
    <section className="card" aria-labelledby="processing-heading" aria-live="polite">
      <div className="row section-heading">
        <div>
          <h2 id="processing-heading">Processing</h2>
          <p className="muted small">{liveDetail ?? `${String(percent)}% complete`}</p>
        </div>
        <strong>{percent}%</strong>
      </div>
      <div
        className="progress"
        role="progressbar"
        aria-label="Dub progress"
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

function StageRow({ job }: { job: Job }) {
  const running = job.status === 'running';
  const mark =
    job.status === 'succeeded' ? '✓' : job.status === 'failed' ? '!' : running ? '●' : '·';
  return (
    <li className={`stage${running ? ' stage--running' : ''}`}>
      <span className="stage__mark" aria-hidden="true">
        {mark}
      </span>
      <span>{job.label}</span>
      <span className="stage__detail">{job.error ?? job.detail ?? job.status}</span>
    </li>
  );
}
