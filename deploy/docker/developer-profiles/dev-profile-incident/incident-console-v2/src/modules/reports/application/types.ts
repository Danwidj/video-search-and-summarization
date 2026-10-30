// SPDX-License-Identifier: Apache-2.0

// Function types the report use cases take from their caller. The caller
// supplies R2 signing, R2 deletion and the agent's embedding call, so no use
// case imports an adapter.

import type { CoverageVerdict, Overview } from '@/modules/reports/domain/envelope';
import type { IncidentId, IncidentRevisionSummary } from '@/modules/reports/domain/IncidentReportRepository';
import type { ReportView } from '@/modules/reports/domain/report-view';
import type { EvidenceEmbedding, EvidenceEntry } from '@/modules/reports/domain/revision';

/** Turns a stored object key into a short-lived URL the browser can play or show. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** Deletes a stored video object and everything derived from it (its thumbnail). */
export type RemoveStoredVideo = (storageKey: string) => Promise<unknown>;

/** The agent's embeddings for the evidence of one stored revision. */
export type EmbedRevisionEvidence = (revisionId: number) => Promise<EvidenceEmbedding[]>;

/** The agent's embeddings for evidence entries that are not stored yet (a revision being saved). */
export type EmbedEvidence = (evidence: EvidenceEntry[]) => Promise<EvidenceEmbedding[]>;

/** One object in the evidence area of R2. */
export interface StoredObject {
  key: string;
  /** null when the store did not say; such an object is never treated as old enough to delete. */
  lastModified: Date | null;
}

/** Lists and removes evidence images in R2. */
export interface EvidenceObjectStore {
  /** Every object whose key starts with `prefix`, across all pages. Throws rather than answer with a partial list. */
  list(prefix: string): Promise<StoredObject[]>;
  remove(key: string): Promise<void>;
}

/** A revision's coverage against the incident's videos now: the verdict and its note ("Does not include: ..."); the note is null when complete. */
export interface CoverageView {
  verdict: CoverageVerdict;
  note: string | null;
}

/** One camera of a revision. */
export interface CameraView {
  /** The real video file name. */
  video: string;
  /** The video is still in the incident; a camera of a removed video is history and cannot be picked. */
  current: boolean;
  /** The camera's report passes incident-contract-v4 validation, so the report panes can show it. */
  valid: boolean;
}

/** One revision of an incident: the overview, the coverage verdict, the cameras and the chosen camera's report. */
export interface IncidentReportView {
  incidentId: IncidentId;
  revision: IncidentRevisionSummary;
  overview: Overview;
  coverage: CoverageView;
  cameras: CameraView[];
  /** The camera shown; null when no camera of the revision can be shown. */
  camera: string | null;
  /** The chosen camera's report in the shape the report panes read; null when no camera is chosen. */
  report: ReportView | null;
  /** The incident's one official revision; never inferred from recency. */
  officialRevisionId: number | null;
  officialSince: string | null;
}

/** One row of the version list, with its coverage verdict against the incident's videos now. */
export interface IncidentVersion extends IncidentRevisionSummary {
  coverage: CoverageView;
}
