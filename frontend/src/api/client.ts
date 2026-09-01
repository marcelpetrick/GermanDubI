/**
 * The typed HTTP client.
 *
 * Every request goes through `request`, so error handling, JSON decoding and the API prefix
 * exist once. The backend guarantees a single error shape, which is why `ApiError` can carry
 * a stable `code` the UI can branch on instead of matching message strings.
 */

import type {
  Artifact,
  Health,
  Meta,
  ProjectDetail,
  ProjectSummary,
  Provider,
  Voice,
  Run,
  Segment,
  SegmentList,
  SegmentUpdated,
  TranslationRevision,
  ApiErrorBody,
} from './types';

export const API_BASE = '/api/v1';

/** An error the backend reported, carrying its stable code. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let body: ApiErrorBody = {
      code: 'unknown_error',
      message: `${response.status} ${response.statusText}`,
      details: {},
    };
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // A non-JSON error body means the server failed before our handlers ran; the status
      // line is the best information available.
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  meta: () => request<Meta>('/meta'),
  health: () => request<Health>('/health'),
  providers: () => request<Provider[]>('/providers'),
  voices: () => request<Voice[]>('/voices'),
  /** Absolute URL of a voice sample, for an <audio> element to fetch itself. */
  voiceSampleUrl: (voice: string) => `${API_BASE}/voices/${encodeURIComponent(voice)}/sample`,

  listProjects: () => request<ProjectSummary[]>('/projects'),
  getProject: (id: string) => request<ProjectDetail>(`/projects/${id}`),
  createProject: (url: string, voice?: string | null) =>
    request<ProjectDetail>('/projects', {
      method: 'POST',
      body: JSON.stringify(voice ? { url, voice } : { url }),
    }),
  deleteProject: (id: string) => request<undefined>(`/projects/${id}`, { method: 'DELETE' }),
  deleteAllProjects: () => request<undefined>('/projects', { method: 'DELETE' }),
  cancelProject: (id: string) => request<undefined>(`/projects/${id}/cancel`, { method: 'POST' }),
  analyzeProject: (id: string) => request<Run>(`/projects/${id}/analyze`, { method: 'POST' }),

  startRun: (id: string) =>
    request<Run>(`/projects/${id}/runs`, { method: 'POST', body: JSON.stringify({}) }),
  latestRun: (id: string) => request<Run | null>(`/projects/${id}/runs/latest`),
  cancelRun: (id: string, runId: string) =>
    request<Run>(`/projects/${id}/runs/${runId}/cancel`, { method: 'POST' }),
  resumeRun: (id: string) => request<Run>(`/projects/${id}/runs/resume`, { method: 'POST' }),

  listSegments: (id: string) => request<SegmentList>(`/projects/${id}/segments`),
  updateSegment: (
    id: string,
    segmentId: string,
    payload: { source_text?: string; translation?: string },
    regenerate = false,
  ) =>
    request<SegmentUpdated>(
      `/projects/${id}/segments/${segmentId}?regenerate=${String(regenerate)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    ),
  retranslateSegment: (id: string, segmentId: string) =>
    request<SegmentUpdated>(`/projects/${id}/segments/${segmentId}/retranslate`, {
      method: 'POST',
    }),
  resynthesizeSegment: (id: string, segmentId: string) =>
    request<SegmentUpdated>(`/projects/${id}/segments/${segmentId}/resynthesize`, {
      method: 'POST',
    }),
  approveSegment: (id: string, segmentId: string) =>
    request<Segment>(`/projects/${id}/segments/${segmentId}/approve`, { method: 'POST' }),
  segmentRevisions: (id: string, segmentId: string) =>
    request<TranslationRevision[]>(`/projects/${id}/segments/${segmentId}/revisions`),

  listArtifacts: (id: string) => request<Artifact[]>(`/projects/${id}/artifacts`),
};

/** URLs for media the browser loads directly, rather than through fetch. */
export const mediaUrl = {
  sourceVideo: (id: string) => `${API_BASE}/projects/${id}/preview/video`,
  export: (id: string) => `${API_BASE}/projects/${id}/preview/export`,
  audio: (id: string, track: 'german' | 'original' | 'background') =>
    `${API_BASE}/projects/${id}/preview/audio/${track}`,
  segmentSpeech: (id: string, segmentId: string) =>
    `${API_BASE}/projects/${id}/segments/${segmentId}/speech`,
  download: (id: string) => `${API_BASE}/projects/${id}/download`,
  events: (id: string) => `${API_BASE}/projects/${id}/events`,
};
