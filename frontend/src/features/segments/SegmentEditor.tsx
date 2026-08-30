import { type FormEvent, useState } from 'react';

import { mediaUrl } from '@/api/client';
import type { Segment } from '@/api/types';
import { ErrorAlert } from '@/components/ErrorAlert';
import { useSegmentAction, useUpdateSegment } from '@/hooks/queries';
import { formatTimestamp } from '@/lib/format';

/** Local editor for one segment; every save creates a backend revision and regeneration run. */
export function SegmentEditor({ projectId, segment }: { projectId: string; segment: Segment }) {
  const [source, setSource] = useState(segment.source_text);
  const [translation, setTranslation] = useState(segment.translation ?? '');
  const update = useUpdateSegment(projectId);
  const action = useSegmentAction(projectId);
  const error = update.error ?? action.error;

  const saveSource = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = source.trim();
    if (value && value !== segment.source_text) {
      update.mutate({ segmentId: segment.id, payload: { source_text: value }, regenerate: true });
    }
  };
  const saveTranslation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = translation.trim();
    if (value && value !== segment.translation) {
      update.mutate({ segmentId: segment.id, payload: { translation: value }, regenerate: true });
    }
  };

  return (
    <aside className="card editor" aria-label={`Edit segment ${String(segment.ordinal + 1)}`}>
      <div className="row section-heading">
        <div>
          <h2>Segment {segment.ordinal + 1}</h2>
          <span className="muted small">
            {formatTimestamp(segment.start_ms)}–{formatTimestamp(segment.end_ms)}
          </span>
        </div>
        <span className={`badge badge--${segment.review_state === 'approved' ? 'ok' : 'warn'}`}>
          {segment.review_state}
        </span>
      </div>

      <form onSubmit={saveSource}>
        <div className="editor__field">
          <label htmlFor={`source-${segment.id}`}>English transcript</label>
          <textarea
            id={`source-${segment.id}`}
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
            }}
          />
        </div>
        <button type="submit" disabled={update.isPending || source.trim() === segment.source_text}>
          Save English & regenerate
        </button>
      </form>

      <form onSubmit={saveTranslation}>
        <div className="editor__field">
          <label htmlFor={`translation-${segment.id}`}>German translation</label>
          <textarea
            id={`translation-${segment.id}`}
            value={translation}
            onChange={(event) => {
              setTranslation(event.target.value);
            }}
          />
        </div>
        <button
          className="primary"
          type="submit"
          disabled={
            update.isPending || !translation.trim() || translation.trim() === segment.translation
          }
        >
          Save German & regenerate
        </button>
      </form>

      {segment.has_speech && (
        <audio controls preload="none" src={mediaUrl.segmentSpeech(projectId, segment.id)} />
      )}
      <div className="row editor__actions">
        <button
          type="button"
          disabled={action.isPending || !segment.translation}
          onClick={() => {
            action.mutate({ segmentId: segment.id, action: 'resynthesize' });
          }}
        >
          Regenerate speech
        </button>
        {segment.translation_origin !== 'human' && (
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => {
              action.mutate({ segmentId: segment.id, action: 'retranslate' });
            }}
          >
            Translate again
          </button>
        )}
        <button
          type="button"
          disabled={action.isPending || !segment.translation || segment.review_state === 'approved'}
          onClick={() => {
            action.mutate({ segmentId: segment.id, action: 'approve' });
          }}
        >
          Approve
        </button>
      </div>
      {error && <ErrorAlert error={error} />}
    </aside>
  );
}
