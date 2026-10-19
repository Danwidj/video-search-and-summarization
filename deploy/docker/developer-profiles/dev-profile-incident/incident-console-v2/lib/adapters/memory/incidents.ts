// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentRepository for use-case tests. It implements the semantics
// the Supabase adapter owns: run scoping, null on a missing run, review writes,
// and the run delete cascading to the review and the run's library summary.
// The library is seeded with summaries as list_incident_report_summaries
// returns them; paging, scope, status and newest/oldest order are modelled,
// and any other filter is refused rather than ignored.

import type {
  IncidentRepository, ReportList, ReportListQuery, ReviewState, RunKey, RunReportRecord, StructuredEditResult,
} from '@/lib/ports';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { ReportLibraryItem } from '@/lib/reports/storage';

const id = (key: RunKey) => `${key.videoId}\u0000${key.modelRunId}`;

const UNMODELLED_FILTERS = [
  'search', 'type', 'severity', 'generatedAfter', 'generatedBefore', 'timeFrom', 'timeTo',
  'entities', 'instruments', 'assets', 'dayOfWeek', 'entityTypes',
] as const;

export class InMemoryIncidentRepository implements IncidentRepository {
  readonly runs = new Map<string, RunReportRecord>();
  readonly reviews = new Map<string, ReviewState>();
  readonly edits: Array<{ key: RunKey; edit: StructuredEdit; editedBy: string }> = [];
  summaries: ReportLibraryItem[];

  constructor(runs: RunReportRecord[] = [], summaries: ReportLibraryItem[] = []) {
    for (const run of runs) {
      this.runs.set(id(run.key), run);
      if (run.review) this.reviews.set(id(run.key), run.review);
    }
    this.summaries = summaries.map((summary) => ({ ...summary }));
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    const unmodelled = UNMODELLED_FILTERS.filter((name) => query[name] !== null);
    if (unmodelled.length || (query.sort !== 'newest' && query.sort !== 'oldest')) {
      throw new Error(`InMemoryIncidentRepository does not model: ${[...unmodelled, query.sort].join(', ')}`);
    }
    const direction = query.sort === 'oldest' ? 1 : -1;
    const matching = this.summaries
      .filter((summary) => (query.scope !== 'official' || summary.isOfficial) && (query.status === null || summary.status === query.status))
      .sort((a, b) => direction * (a.generatedAt ?? '').localeCompare(b.generatedAt ?? '') || a.reportId.localeCompare(b.reportId));
    // The RPC clamps the page size to 1-1000 and the page to at least 1.
    const size = Math.min(Math.max(query.pageSize, 1), 1000);
    const start = (Math.max(query.page, 1) - 1) * size;
    return {
      items: matching.slice(start, start + size).map((summary) => ({ ...summary })),
      totalItems: matching.length,
      incidentTypes: [...new Set(this.summaries.map((summary) => summary.incident_type))].sort(),
    };
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
    this.summaries = this.summaries.filter((summary) => summary.videoId !== key.videoId || summary.modelRunId !== key.modelRunId);
  }
}
