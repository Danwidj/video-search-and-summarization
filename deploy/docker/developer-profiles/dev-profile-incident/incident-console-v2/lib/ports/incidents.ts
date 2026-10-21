// SPDX-License-Identifier: Apache-2.0

// IncidentRepository: the report library, and one run's report, its review
// state, structured edits and run deletes. Every per-run method is scoped to
// one (videoId, modelRunId) run: a video has many runs, and incidents are keyed
// by (incident_id, model_run_id).

import type { Page, RunKey } from '@/lib/ports/common';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { StructuredAsset, StructuredEntity, StructuredIncident, StructuredInstrument } from '@/lib/reports/report-view';
import type { RunNotes } from '@/lib/reports/run-notes';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';

export type ReportSort = 'newest' | 'oldest' | 'severity-high' | 'severity-low' | 'confidence-high' | 'confidence-low';

/** The report library's filters, validated by the route; null means no filter. */
export interface ReportListQuery {
  page: number;
  pageSize: number;
  /** Matched against title, type, summary, filename and evidence text. */
  search: string | null;
  type: string | null;
  /** A band ('low' | 'medium' | 'high') or an exact level ('1' to '5'). */
  severity: string | null;
  /** A review status; an unknown value matches nothing. */
  status: string | null;
  /** Bounds on the report's generation time, as stored timestamps (naive UTC). */
  generatedAfter: string | null;
  generatedBefore: string | null;
  /** Time-of-day bounds, read in `timezone`. */
  timeFrom: string | null;
  timeTo: string | null;
  /** Evidence text: substrings, or exact names when evidenceMatch is 'exact'. */
  entities: string[] | null;
  instruments: string[] | null;
  assets: string[] | null;
  /** 0 (Sunday) to 6, in `timezone`. */
  dayOfWeek: number | null;
  sort: ReportSort;
  /** 'official' keeps only each video's selected official report. */
  scope: 'all' | 'official';
  /** Canonical entity types (human, animal, unknown). */
  entityTypes: string[] | null;
  evidenceMatch: 'contains' | 'exact';
  timezone: string;
}

/** One page of the report library. Thumbnails are not signed here. */
export interface ReportList extends Page<ReportLibraryItem> {
  /** Every incident type in the store, for the type filter. */
  incidentTypes: string[];
}

/** One review_status row: three statuses plus who verified and edited the report, and when. */
export interface ReviewState {
  status: ReviewStatus;
  verifiedBy: string | null;
  verifiedAt: string | null;
  editedBy: string | null;
  editedAt: string | null;
}

/** The video's explicit official-report selection (D6). */
export interface OfficialSelectionState {
  officialRunId: string | null;
  selectedBy: string | null;
  selectedAt: string | null;
}

/**
 * Everything stored for one run, translated: the facts the report view is
 * built from. Class A is already normalised (canonical types, seconds) and the
 * immutable model_runs.notes are already decoded.
 */
export interface RunReportRecord {
  key: RunKey;
  video: {
    /** videos.filepath when it is a non-empty string, else null. */
    storageKey: string | null;
    filename: string;
    official: OfficialSelectionState;
  };
  modelRun: { modelName: string | null; promptVersion: string | null; runAt: string | null; notes: RunNotes };
  incident: StructuredIncident;
  entities: StructuredEntity[];
  instruments: StructuredInstrument[];
  assets: StructuredAsset[];
  review: ReviewState | null;
  report: { reportId: string | null; generatedAt: string | null } | null;
}

/** The result of saving the reviewer's version of a run. */
export interface StructuredEditResult {
  incidentId: string;
  modelRunId: string;
  editedBy: string;
  editedAt: string;
  duration: number;
  /** 1 for the first saved reviewer version, then +1 per save. */
  revision: number;
  /** The review status after the save: an edit sends a verified report back to 'under review'. */
  status: ReviewStatus;
}

/** One atomic review transition. Never changes editedBy/editedAt, which mean "last content edit". */
export interface ReviewTransition {
  /** False when the run already had the status; nothing was written. */
  changed: boolean;
  status: ReviewStatus;
  /** Set only when the transition verified the report. */
  verifiedBy: string | null;
  verifiedAt: string | null;
  /** Verifying a report with no reviewer version first copied the AI report into one. */
  humanVersionCreated: boolean;
}

export interface IncidentRepository {
  /** One filtered, sorted page of report summaries (runs with a report). */
  listReports(query: ReportListQuery): Promise<ReportList>;
  /**
   * Null when the run, its video or its incident is missing. The incident and
   * its evidence are the effective report: the reviewer's version when the run
   * has one, otherwise the AI's.
   */
  getRunReport(key: RunKey): Promise<RunReportRecord | null>;
  /** True when the run has an incident row. */
  runExists(key: RunKey): Promise<boolean>;
  getReview(key: RunKey): Promise<ReviewState | null>;
  /**
   * Moves the run to `status` in one transaction: verifying stamps the
   * verifier, any other status clears it, and the edit stamps are kept.
   * Verifying a report with no reviewer version first copies the AI report
   * into one. Throws StoreRejection: 'not-found' for a run with no
   * incident, 'invalid' when verifying an AI report that cannot be a reviewer
   * version as it stands (e.g. a legacy run with no type or an unrated
   * instrument; it must be edited first).
   */
  setReviewStatus(key: RunKey, status: ReviewStatus, reviewer: string): Promise<ReviewTransition>;
  /**
   * Atomically saves the reviewer's version of the run (created on the first
   * edit) and stamps editedBy/editedAt; an edit of a verified report sends it
   * back to 'under review'. Never touches the AI report or model_runs.notes.
   * Throws StoreRejection: 'not-found' for a run with no incident, 'invalid'
   * for an edit the store refuses (e.g. a source_id that names no AI item).
   */
  applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult>;
  /** Deletes the run's incident; its evidence, review and report rows cascade. */
  deleteRun(key: RunKey): Promise<void>;
}
