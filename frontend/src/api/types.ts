/** Friendly aliases for the backend-owned shapes generated from OpenAPI. */
import type { components } from './generated/schema';

type Schemas = components['schemas'];

export type ProjectState = Schemas['ProjectDetail']['state'];
export type JobStatus = Schemas['JobDetail']['status'];
export type Stage = Schemas['JobDetail']['stage'];
export type SegmentStatus = Schemas['SegmentDetail']['status'];
export type ReviewState = Schemas['SegmentDetail']['review_state'];
export type CaptionTrack = Schemas['CaptionTrackModel'];
export type SourceMedia = Schemas['SourceMediaModel'];
export type ProjectSummary = Schemas['ProjectSummary'];
export type ProjectDetail = Schemas['ProjectDetail'];
export type Job = Schemas['JobDetail'];
export type Run = Schemas['RunDetail'];
export type DurationFit = Schemas['DurationFitModel'];
export type Segment = Schemas['SegmentDetail'];
export type SegmentSummary = Schemas['SegmentSummaryModel'];
export type SegmentList = Schemas['SegmentListResponse'];
export type SegmentUpdated = Schemas['SegmentUpdatedResponse'];
export type TranslationRevision = Schemas['TranslationRevisionModel'];
export type Meta = Schemas['MetaResponse'];
export type Health = Schemas['HealthResponse'];
export type Provider = Schemas['ProviderStatus'];
export type Voice = Schemas['VoiceStatus'];
export type Artifact = Schemas['ArtifactModel'];
export type ApiErrorBody = Schemas['ErrorResponse'];
