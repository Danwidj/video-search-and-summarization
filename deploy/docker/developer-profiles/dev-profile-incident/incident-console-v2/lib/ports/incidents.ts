// SPDX-License-Identifier: Apache-2.0

// IncidentRepository: one run's report, its review state, structured edits and
// run deletes. Every method is scoped to one (videoId, modelRunId) run: a video
// has many runs, and incidents are keyed by (incident_id, model_run_id).
// Report-library listing joins this port when app/api/reports/route.ts moves.

import type { RunKey } from '@/lib/ports/common';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { StructuredAsset, StructuredEntity, StructuredIncident, StructuredInstrument } from '@/lib/reports/report-view';
import type { RunNotes } from '@/lib/reports/run-notes';
import type { ReviewStatus } from '@/lib/reports/storage';

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

/** apply_structured_report_edit's result. */
export interface StructuredEditResult {
  incidentId: string;
  modelRunId: string;
  editedBy: string;
  editedAt: string;
  duration: number;
}

export interface IncidentRepository {
  /** Null when the run, its video or its incident is missing. */
  getRunReport(key: RunKey): Promise<RunReportRecord | null>;
  /** True when the run has an incident row. */
  runExists(key: RunKey): Promise<boolean>;
  getReview(key: RunKey): Promise<ReviewState | null>;
  /** Writes all five review columns for the run. */
  saveReview(key: RunKey, review: ReviewState): Promise<void>;
  /** Atomic Class A edit; never touches model_runs.notes. */
  applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult>;
  /** Deletes the run's incident; its evidence, review and report rows cascade. */
  deleteRun(key: RunKey): Promise<void>;
}
