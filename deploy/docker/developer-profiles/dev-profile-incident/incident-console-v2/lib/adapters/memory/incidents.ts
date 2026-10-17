// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentRepository for use-case tests. It implements the semantics
// the Supabase adapter owns: run scoping, null on a missing run, review writes,
// and the run delete cascading to the review.

import type { IncidentRepository, ReviewState, RunKey, RunReportRecord, StructuredEditResult } from '@/lib/ports';
import type { StructuredEdit } from '@/lib/reports/edit-draft';

const id = (key: RunKey) => `${key.videoId}\u0000${key.modelRunId}`;

export class InMemoryIncidentRepository implements IncidentRepository {
  readonly runs = new Map<string, RunReportRecord>();
  readonly reviews = new Map<string, ReviewState>();
  readonly edits: Array<{ key: RunKey; edit: StructuredEdit; editedBy: string }> = [];

  constructor(runs: RunReportRecord[] = []) {
    for (const run of runs) {
      this.runs.set(id(run.key), run);
      if (run.review) this.reviews.set(id(run.key), run.review);
    }
  }

  async getRunReport(key: RunKey): Promise<RunReportRecord | null> {
    const run = this.runs.get(id(key));
    return run ? { ...run, review: this.reviews.get(id(key)) ?? null } : null;
  }

  async runExists(key: RunKey): Promise<boolean> {
    return this.runs.has(id(key));
  }

  async getReview(key: RunKey): Promise<ReviewState | null> {
    return this.reviews.get(id(key)) ?? null;
  }

  async saveReview(key: RunKey, review: ReviewState): Promise<void> {
    this.reviews.set(id(key), { ...review });
  }

  async applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult> {
    if (!this.runs.has(id(key))) throw new Error('Report not found for this video and model run');
    this.edits.push({ key, edit, editedBy });
    const editedAt = new Date().toISOString().replace('Z', '');
    this.reviews.set(id(key), { ...(this.reviews.get(id(key)) ?? { status: 'unreviewed', verifiedBy: null, verifiedAt: null }), editedBy, editedAt });
    return { incidentId: key.videoId, modelRunId: key.modelRunId, editedBy, editedAt, duration: edit.incident.end_timestamp - edit.incident.start_timestamp };
  }

  async deleteRun(key: RunKey): Promise<void> {
    this.runs.delete(id(key));
    this.reviews.delete(id(key));
  }
}
