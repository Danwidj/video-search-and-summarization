// SPDX-License-Identifier: Apache-2.0

// ModelRunRepository: the record of one model call. Its id is readable,
// `<subject>@<UTC timestamp>`, where the subject is a video name or
// `incident-<id>` for a synthesis run.

export interface ModelRun {
  id: string;
  modelName: string;
  modelVersion: string | null;
  promptVersion: string | null;
  /** UTC instant of the run, ISO 8601. */
  runAt: string;
  /** The run's immutable record text; null when none was written. */
  notes: string | null;
}

/** The readable run id for a subject at an instant: `<subject>@<UTC ISO timestamp>`. */
export function modelRunId(subject: string, at: Date | string): string {
  const instant = typeof at === 'string' ? at : at.toISOString();
  return `${subject}@${instant}`;
}

/** The subject a synthesis run is named after. */
export const incidentRunSubject = (incidentId: number): string => `incident-${incidentId}`;

export interface ModelRunRepository {
  /** Records a run, or replaces the one with the same id (a re-registered run is updated in place, never deleted). */
  recordRun(run: ModelRun): Promise<void>;
  getRun(id: string): Promise<ModelRun | null>;
}
