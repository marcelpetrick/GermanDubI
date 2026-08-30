import { Link, useParams } from 'react-router-dom';

import { mediaUrl } from '@/api/client';
import { ErrorAlert } from '@/components/ErrorAlert';
import { PipelineProgress } from '@/features/processing/PipelineProgress';
import { SegmentWorkspace } from '@/features/segments/SegmentWorkspace';
import {
  useAnalyzeProject,
  useArtifacts,
  useCancelRun,
  useLatestRun,
  useProject,
  useResumeRun,
  useSegments,
  useStartRun,
} from '@/hooks/queries';
import { useProjectEvents } from '@/hooks/useProjectEvents';
import { formatDuration } from '@/lib/format';

const ACTIVE_STATES = new Set(['probing', 'processing']);

/** State-aware workspace for one dubbing project. */
export function ProjectPage() {
  const { projectId } = useParams();
  const project = useProject(projectId);
  const state = project.data?.state;
  const active = state ? ACTIVE_STATES.has(state) : false;
  const run = useLatestRun(projectId, active);
  const segments = useSegments(projectId, state === 'review' || state === 'complete');
  const artifacts = useArtifacts(projectId, state === 'review' || state === 'complete');
  const analyze = useAnalyzeProject(projectId ?? '');
  const start = useStartRun(projectId ?? '');
  const cancel = useCancelRun(projectId ?? '');
  const resume = useResumeRun(projectId ?? '');
  const live = useProjectEvents(projectId ?? null, active);

  if (!projectId) return <ErrorAlert error={new Error('The project identifier is missing.')} />;
  if (project.isPending) return <p className="muted">Loading project…</p>;
  if (project.error) return <ErrorAlert error={project.error} />;
  if (!project.data) return null;

  const item = project.data;
  const mutationError = analyze.error ?? start.error ?? cancel.error ?? resume.error;

  return (
    <div className="stack">
      <nav className="small" aria-label="Breadcrumb">
        <Link to="/">Projects</Link> / <span>{item.title}</span>
      </nav>

      <section className="card project-header">
        {item.thumbnail_url && <img src={item.thumbnail_url} alt="" />}
        <div className="stack project-header__body">
          <div>
            <div className="row">
              <h1>{item.title}</h1>
              <span className={`badge badge--${statusTone(item.state)}`}>{item.state}</span>
            </div>
            <p className="muted source-locator">{item.source_locator}</p>
          </div>
          {item.media && (
            <div className="row small muted">
              <span>{formatDuration(item.media.duration_ms)}</span>
              {item.media.uploader && <span>by {item.media.uploader}</span>}
              <span>
                {item.media.has_english_captions
                  ? item.media.best_captions_are_automatic
                    ? 'Automatic English captions'
                    : 'Manual English captions'
                  : 'Speech recognition required'}
              </span>
            </div>
          )}
          <ProjectActions
            state={item.state}
            pending={analyze.isPending || start.isPending || cancel.isPending || resume.isPending}
            runId={run.data?.id ?? null}
            projectId={projectId}
            onAnalyze={() => {
              analyze.mutate();
            }}
            onStart={() => {
              start.mutate();
            }}
            onCancel={(runId) => {
              cancel.mutate(runId);
            }}
            onResume={() => {
              resume.mutate();
            }}
          />
          {item.error && <ErrorAlert error={new Error(item.error)} />}
          {mutationError && <ErrorAlert error={mutationError} />}
        </div>
      </section>

      {run.data && (active || run.data.failed || run.data.cancelled) && (
        <PipelineProgress run={run.data} liveDetail={eventDetail(live?.payload)} />
      )}

      {(state === 'review' || state === 'complete') && (
        <section className="card preview" aria-labelledby="preview-heading">
          <div className="row section-heading">
            <div>
              <h2 id="preview-heading">German preview</h2>
              <p className="muted small">The export includes German and original audio tracks.</p>
            </div>
            <a className="button button--primary" href={mediaUrl.download(projectId)} download>
              Download export
            </a>
          </div>
          <video controls preload="metadata" src={mediaUrl.export(projectId)}>
            <track kind="captions" />
          </video>
          {artifacts.data && (
            <p className="muted small">{artifacts.data.length} current artifacts with provenance</p>
          )}
        </section>
      )}

      {(state === 'review' || state === 'complete') && (
        <SegmentWorkspace
          projectId={projectId}
          data={segments.data}
          loading={segments.isPending}
          error={segments.error}
        />
      )}
    </div>
  );
}

function ProjectActions({
  state,
  pending,
  runId,
  projectId,
  onAnalyze,
  onStart,
  onCancel,
  onResume,
}: {
  state: string;
  pending: boolean;
  runId: string | null;
  projectId: string;
  onAnalyze: () => void;
  onStart: () => void;
  onCancel: (runId: string) => void;
  onResume: () => void;
}) {
  if (state === 'new') {
    return (
      <button className="primary" disabled={pending} onClick={onAnalyze}>
        Analyze source
      </button>
    );
  }
  if (state === 'ready') {
    return (
      <button className="primary" disabled={pending} onClick={onStart}>
        Create German dub
      </button>
    );
  }
  if (ACTIVE_STATES.has(state) && runId) {
    return (
      <button
        disabled={pending}
        onClick={() => {
          onCancel(runId);
        }}
      >
        Cancel processing
      </button>
    );
  }
  if (state === 'failed' || state === 'cancelled') {
    return (
      <button className="primary" disabled={pending} onClick={onResume}>
        Resume unfinished work
      </button>
    );
  }
  if (state === 'complete') {
    return (
      <a className="button" href={mediaUrl.download(projectId)}>
        Download
      </a>
    );
  }
  return null;
}

function statusTone(state: string): string {
  if (state === 'failed') return 'danger';
  if (state === 'probing' || state === 'processing') return 'running';
  if (state === 'review') return 'warn';
  return 'ok';
}

function eventDetail(payload: Record<string, unknown> | undefined): string | null {
  if (!payload) return null;
  const detail = payload.detail ?? payload.message;
  return typeof detail === 'string' ? detail : null;
}
