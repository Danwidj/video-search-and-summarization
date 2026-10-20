// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentRepository for use-case tests. It implements the semantics
// the Supabase adapter owns: run scoping, null on a missing run, the reviewer
// version (an edit or a verification never changes the AI report; the report
// read is the reviewer's version when there is one), atomic review transitions,
// and the run delete cascading to the review, the reviewer version and the
// run's library summary.
// The library is seeded with summaries as list_incident_report_summaries
// returns them; paging, scope, status and newest/oldest order are modelled,
// and any other filter is refused rather than ignored.

import { nextReviewState } from '@/lib/application/reports';
import type {
  IncidentRepository, ReportList, ReportListQuery, ReviewState, ReviewTransition, RunKey, RunReportRecord, StructuredEditResult,
} from '@/lib/ports';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';

const id = (key: RunKey) => `${key.videoId}\u0000${key.modelRunId}`;

/** The reviewer's version of one run: the report fields of a RunReportRecord, plus its save count. */
type HumanVersion = Pick<RunReportRecord, 'incident' | 'entities' | 'instruments' | 'assets'> & { revision: number };

/** Stored timestamps are naive UTC, as Postgres returns them. */
const storedNow = () => new Date().toISOString().replace('Z', '');

const UNMODELLED_FILTERS = [
  'search', 'type', 'severity', 'generatedAfter', 'generatedBefore', 'timeFrom', 'timeTo',
  'entities', 'instruments', 'assets', 'dayOfWeek', 'entityTypes',
] as const;

export class InMemoryIncidentRepository implements IncidentRepository {
  /** The AI reports, as analysis stored them; edits and verifications never change them. */
  readonly runs = new Map<string, RunReportRecord>();
  readonly humanVersions = new Map<string, HumanVersion>();
  readonly reviews = new Map<string, ReviewState>();
  readonly edits: Array<{ key: RunKey; edit: StructuredEdit; editedBy: string }> = [];
  summaries: ReportLibraryItem[];
  now = storedNow;

  constructor(runs: RunReportRecord[] = [], summaries: ReportLibraryItem[] = []) {
    for (const run of runs) {
      this.runs.set(id(run.key), run);
      if (run.review) this.reviews.set(id(run.key), run.review);
    }
    this.summaries = summaries.map((summary) => ({ ...summary }));
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    const unmodelled: string[] = UNMODELLED_FILTERS.filter((name) => query[name] !== null);
    if (query.sort !== 'newest' && query.sort !== 'oldest') unmodelled.push(`sort ${query.sort}`);
    if (unmodelled.length) throw new Error(`InMemoryIncidentRepository does not model: ${unmodelled.join(', ')}`);
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
    if (!run) return null;
    const human = this.humanVersions.get(id(key));
    const report = human ? { incident: human.incident, entities: human.entities, instruments: human.instruments, assets: human.assets } : {};
    return { ...run, ...report, review: this.reviews.get(id(key)) ?? null };
  }

  async runExists(key: RunKey): Promise<boolean> {
    return this.runs.has(id(key));
  }

  async getReview(key: RunKey): Promise<ReviewState | null> {
    return this.reviews.get(id(key)) ?? null;
  }

  async setReviewStatus(key: RunKey, status: ReviewStatus, reviewer: string): Promise<ReviewTransition> {
    const run = this.runs.get(id(key));
    if (!run) throw new Error('Report not found for this video and model run');
    const next = nextReviewState(this.reviews.get(id(key)) ?? null, status, reviewer.trim(), this.now());
    if (!next) return { changed: false, status, verifiedBy: null, verifiedAt: null, humanVersionCreated: false };
    const humanVersionCreated = status === 'verified' && !this.humanVersions.has(id(key));
    if (humanVersionCreated) {
      const { incident, entities, instruments, assets } = run;
      this.humanVersions.set(id(key), { incident, entities, instruments, assets, revision: 1 });
    }
    this.reviews.set(id(key), next);
    return { changed: true, status, verifiedBy: next.verifiedBy, verifiedAt: next.verifiedAt, humanVersionCreated };
  }

  async applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult> {
    const run = this.runs.get(id(key));
    if (!run) throw new Error('Report not found for this video and model run');
    this.edits.push({ key, edit, editedBy });
    const editor = editedBy.trim();
    const editedAt = this.now();
    const { incident } = edit;
    const duration = incident.end_timestamp - incident.start_timestamp;
    const revision = (this.humanVersions.get(id(key))?.revision ?? 0) + 1;
    this.humanVersions.set(id(key), {
      incident: {
        type: incident.type, startSeconds: incident.start_timestamp, endSeconds: incident.end_timestamp, duration,
        description: incident.description, severityLevel: incident.severity_level, confidenceScore: run.incident.confidenceScore,
      },
      entities: edit.entities.map((entity) => ({ entityId: entity.entity_id, type: entity.type, description: entity.description })),
      instruments: edit.instruments.map((instrument) => ({
        instrumentId: instrument.instrument_id, entityId: instrument.entity_id, name: instrument.name,
        description: instrument.description, threatLevel: instrument.threat_level,
      })),
      assets: edit.assets.map((asset) => ({ assetId: asset.asset_id, name: asset.name, description: asset.description })),
      revision,
    });
    // An edit sends a verified report back to 'under review' and clears the verifier.
    const current = this.reviews.get(id(key)) ?? { status: 'unreviewed', verifiedBy: null, verifiedAt: null, editedBy: null, editedAt: null };
    const review: ReviewState = current.status === 'verified'
      ? { status: 'under review', verifiedBy: null, verifiedAt: null, editedBy: editor, editedAt }
      : { ...current, editedBy: editor, editedAt };
    this.reviews.set(id(key), review);
    return { incidentId: key.videoId, modelRunId: key.modelRunId, editedBy: editor, editedAt, duration, revision, status: review.status };
  }

  async deleteRun(key: RunKey): Promise<void> {
    this.runs.delete(id(key));
    this.humanVersions.delete(id(key));
    this.reviews.delete(id(key));
    this.summaries = this.summaries.filter((summary) => summary.videoId !== key.videoId || summary.modelRunId !== key.modelRunId);
  }
}
