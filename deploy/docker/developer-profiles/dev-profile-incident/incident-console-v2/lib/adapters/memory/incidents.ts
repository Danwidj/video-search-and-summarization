// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentRepository for use-case tests. It implements the semantics
// the Supabase adapter owns: run scoping, null on a missing run, the reviewer
// version (an edit or a verification never changes the AI report; the report
// read is the reviewer's version when there is one; each reviewer item keeps
// the AI item it came from), atomic review transitions (verifying copies the
// AI report into a renumbered reviewer version, or refuses one that must be
// edited first), and the run delete cascading to the review, the reviewer
// version and the run's library summary.
// The library is seeded with summaries as list_incident_report_summaries
// returns them; paging, scope, status and newest/oldest order are modelled,
// and any other filter is refused rather than ignored.

import {
  StoreRejection,
  type IncidentRepository, type ReportList, type ReportListQuery, type ReviewState, type ReviewTransition, type RunKey, type RunReportRecord,
  type StructuredEditResult,
} from '@/lib/ports';
import { EDITABLE_ENTITY_TYPES, EDITABLE_INCIDENT_TYPES, type StructuredEdit } from '@/lib/reports/edit-draft';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';

const id = (key: RunKey) => `${key.videoId}\u0000${key.modelRunId}`;

/** The reviewer's version of one run: the report fields of a RunReportRecord, plus its save count. */
type HumanVersion = Pick<RunReportRecord, 'incident' | 'entities' | 'instruments' | 'assets'> & { revision: number };

/** Stored timestamps are naive UTC, as Postgres returns them. */
const storedNow = () => new Date().toISOString().replace('Z', '');

const rated = (level: number | null) => level !== null && level >= 1 && level <= 5;

/**
 * set_review_status's transition rule: null when the status is unchanged, a
 * run without a review counting as 'unreviewed'; otherwise the reviewer
 * becomes the verifier only when verifying. The edit stamps are kept: they
 * mean "last content edit", and a status change is not one.
 */
function nextReviewState(current: ReviewState | null, status: ReviewStatus, reviewer: string, now: string): ReviewState | null {
  if ((current?.status ?? 'unreviewed') === status) return null;
  const verified = status === 'verified';
  return {
    status,
    editedBy: current?.editedBy ?? null,
    editedAt: current?.editedAt ?? null,
    verifiedBy: verified ? reviewer : null,
    verifiedAt: verified ? now : null,
  };
}

/**
 * The reviewer version verifying copies from the AI report (create_human_report_from_ai):
 * items keep their order, are renumbered E#/I#/A# and name the AI item they came from.
 * Refused when the AI report is not a valid reviewer version as it stands.
 */
function humanVersionFromAi(run: RunReportRecord): HumanVersion {
  const { incident, entities, instruments, assets } = run;
  const entityIds = new Map(entities.map((entity, index) => [entity.entityId, `E${index + 1}`]));
  const valid = (EDITABLE_INCIDENT_TYPES as readonly (string | null)[]).includes(incident.type)
    && incident.startSeconds !== null && incident.endSeconds !== null && incident.endSeconds >= incident.startSeconds
    && rated(incident.severityLevel) && incident.description !== null
    && entities.every((entity) => (EDITABLE_ENTITY_TYPES as readonly string[]).includes(entity.type))
    && instruments.every((instrument) => rated(instrument.threatLevel) && (instrument.entityId === null || entityIds.has(instrument.entityId)));
  if (!valid) throw new StoreRejection('invalid', `The AI report of run ${run.key.modelRunId} cannot be verified as it stands; edit it first`);
  return {
    incident,
    entities: entities.map((entity, index) => ({ ...entity, entityId: `E${index + 1}`, sourceId: entity.entityId })),
    instruments: instruments.map((instrument, index) => ({
      ...instrument, instrumentId: `I${index + 1}`, sourceId: instrument.instrumentId, entityId: instrument.entityId === null ? null : entityIds.get(instrument.entityId)!,
    })),
    assets: assets.map((asset, index) => ({ ...asset, assetId: `A${index + 1}`, sourceId: asset.assetId })),
    revision: 1,
  };
}

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
    if (!run) throw new StoreRejection('not-found', 'Report not found for this video and model run');
    const next = nextReviewState(this.reviews.get(id(key)) ?? null, status, reviewer.trim(), this.now());
    if (!next) return { changed: false, status, verifiedBy: null, verifiedAt: null, humanVersionCreated: false };
    const humanVersionCreated = status === 'verified' && !this.humanVersions.has(id(key));
    if (humanVersionCreated) this.humanVersions.set(id(key), humanVersionFromAi(run));
    this.reviews.set(id(key), next);
    return { changed: true, status, verifiedBy: next.verifiedBy, verifiedAt: next.verifiedAt, humanVersionCreated };
  }

  async applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult> {
    const run = this.runs.get(id(key));
    if (!run) throw new StoreRejection('not-found', 'Report not found for this video and model run');
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
      entities: edit.entities.map((entity) => ({
        entityId: entity.entity_id, sourceId: entity.source_id,
        type: entity.type, description: entity.description,
      })),
      instruments: edit.instruments.map((instrument) => ({
        instrumentId: instrument.instrument_id, sourceId: instrument.source_id,
        entityId: instrument.entity_id, name: instrument.name, description: instrument.description, threatLevel: instrument.threat_level,
      })),
      assets: edit.assets.map((asset) => ({
        assetId: asset.asset_id, sourceId: asset.source_id,
        name: asset.name, description: asset.description,
      })),
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
