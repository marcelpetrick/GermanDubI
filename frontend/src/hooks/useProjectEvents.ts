/**
 * Subscribing to a project's progress stream.
 *
 * The backend is authoritative for state, so this hook does not accumulate its own copy of
 * the pipeline. It listens for events and invalidates the relevant queries, letting TanStack
 * Query refetch the truth. That keeps one source of state instead of two that can disagree.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { mediaUrl } from '@/api/client';

/** The most recent event, for showing live detail on the processing screen. */
export interface LiveEvent {
  kind: string;
  payload: Record<string, unknown>;
}

/**
 * Follow a project's server-sent progress events.
 *
 * @param projectId - The project to follow, or null to not subscribe.
 * @param active - Whether the stream should be open. Closing it when the run is finished
 *   avoids holding a connection open for a project nobody is watching.
 */
export function useProjectEvents(projectId: string | null, active: boolean): LiveEvent | null {
  const queryClient = useQueryClient();
  const [latest, setLatest] = useState<LiveEvent | null>(null);
  // Kept in a ref so reconnecting does not re-run this effect and drop the stream.
  const lastEventId = useRef<string | null>(null);

  useEffect(() => {
    if (!projectId || !active) return;

    const source = new EventSource(mediaUrl.events(projectId));

    const refresh = (kind: string) => {
      void queryClient.invalidateQueries({ queryKey: ['run', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      if (
        kind === 'segments_ready' ||
        kind === 'translation_ready' ||
        kind === 'speech_ready' ||
        kind === 'fit_ready' ||
        kind === 'run_finished'
      ) {
        void queryClient.invalidateQueries({ queryKey: ['segments', projectId] });
      }
    };

    const handle = (event: MessageEvent<string>) => {
      lastEventId.current = event.lastEventId;
      let payload: Record<string, unknown> = {};
      try {
        payload = JSON.parse(event.data) as Record<string, unknown>;
      } catch {
        // A malformed frame is not worth failing the whole stream over.
      }
      setLatest({ kind: event.type, payload });
      refresh(event.type);
    };

    const kinds = [
      'project_created',
      'analysis_requested',
      'source_analysed',
      'run_started',
      'stage_started',
      'stage_progress',
      'stage_finished',
      'stage_failed',
      'stage_retrying',
      'stage_cancelled',
      'segments_ready',
      'transcript_ready',
      'translation_ready',
      'speech_ready',
      'fit_ready',
      'separation_ready',
      'separation_skipped',
      'mix_ready',
      'qa_complete',
      'export_ready',
      'run_finished',
      'run_cancelled',
    ];
    for (const kind of kinds) source.addEventListener(kind, handle as EventListener);

    // The server closes the stream on a schedule; EventSource reconnects on its own and
    // replays from Last-Event-ID, so an error here is normal and needs no handling.
    return () => {
      for (const kind of kinds) source.removeEventListener(kind, handle as EventListener);
      source.close();
    };
  }, [projectId, active, queryClient]);

  return latest;
}
