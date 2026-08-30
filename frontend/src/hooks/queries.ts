/**
 * Server state, owned by TanStack Query.
 *
 * Nothing here caches derived state locally. The backend is authoritative; a component that
 * needs to know something asks a query, and a mutation invalidates what it changed.
 */

import { skipToken, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import type { Segment, SegmentUpdated } from '@/api/types';

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity });
}

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 60_000 });
}

export function useProviders() {
  return useQuery({ queryKey: ['providers'], queryFn: api.providers, staleTime: 60_000 });
}

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: api.listProjects });
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: ['project', id],
    queryFn: id ? () => api.getProject(id) : skipToken,
  });
}

/**
 * A project's most recent run.
 *
 * Polled slowly as a safety net: progress normally arrives over SSE, but a dropped stream
 * should degrade to a stale screen rather than a frozen one.
 */
export function useLatestRun(id: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ['run', id],
    queryFn: id ? () => api.latestRun(id) : skipToken,
    refetchInterval: active ? 5_000 : false,
  });
}

export function useSegments(id: string | undefined) {
  return useQuery({
    queryKey: ['segments', id],
    queryFn: id ? () => api.listSegments(id) : skipToken,
  });
}

export function useArtifacts(id: string | undefined) {
  return useQuery({
    queryKey: ['artifacts', id],
    queryFn: id ? () => api.listArtifacts(id) : skipToken,
  });
}

export function useCreateAndAnalyzeProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (url: string) => {
      const project = await api.createProject(url);
      await api.analyzeProject(project.id);
      return project;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  });
}

export function useAnalyzeProject(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.analyzeProject(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['project', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}

export function useStartRun(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.startRun(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['project', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}

export function useCancelRun(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.cancelRun(id, runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['project', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}

export function useResumeRun(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.resumeRun(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['project', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}

/**
 * Correct a segment.
 *
 * `regenerate` is what turns an edit into a visible result: the backend queues exactly the
 * stages the edit invalidated and nothing more.
 */
export function useUpdateSegment(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      segmentId: string;
      payload: { source_text?: string; translation?: string };
      regenerate?: boolean;
    }) => api.updateSegment(id, input.segmentId, input.payload, input.regenerate ?? false),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['segments', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
      await queryClient.invalidateQueries({ queryKey: ['project', id] });
    },
  });
}

export function useSegmentAction(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      segmentId: string;
      action: 'retranslate' | 'resynthesize' | 'approve';
    }): Promise<SegmentUpdated | Segment> => {
      if (input.action === 'retranslate') {
        return await api.retranslateSegment(id, input.segmentId);
      }
      if (input.action === 'resynthesize') {
        return await api.resynthesizeSegment(id, input.segmentId);
      }
      return await api.approveSegment(id, input.segmentId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['segments', id] });
      await queryClient.invalidateQueries({ queryKey: ['run', id] });
    },
  });
}
