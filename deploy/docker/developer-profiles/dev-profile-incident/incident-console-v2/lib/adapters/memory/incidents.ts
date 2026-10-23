// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentRepository for use-case tests. It implements the semantics
// the Supabase adapter owns: revisions are append-only and numbered per video;
// getRevision with no id reads the official revision, else the newest; a human
// revision takes its parent's run and refuses an unknown video or parent or an
// empty reviewer name.
// The library is seeded with summaries as list_incident_report_summaries
// returns them; paging, scope, kind and newest/oldest order are modelled, and
// any other filter is refused rather than ignored.

import {
  StoreRejection,
  type HumanRevisionInput, type IncidentRepository, type ReportList, type ReportListQuery, type RevisionRecord,
} from '@/lib/ports';
import { structuredFromPayload } from '@/lib/reports/payload-view';
import type { RevisionSummary } from '@/lib/reports/revision';
import type { ReportLibraryItem } from '@/lib/reports/storage';

/** Stored timestamps are naive UTC, as Postgres returns them. */
const storedNow = () => new Date().toISOString().replace('Z', '');

const UNMODELLED_FILTERS = [
  'search', 'type', 'severity', 'generatedAfter', 'generatedBefore', 'timeFrom', 'timeTo',
  'entities', 'instruments', 'assets', 'dayOfWeek', 'entityTypes',
] as const;

export class InMemoryIncidentRepository implements IncidentRepository {
  /** Every revision of every video, oldest first. */
  readonly revisions: RevisionRecord[] = [];
  readonly saved: HumanRevisionInput[] = [];
  summaries: ReportLibraryItem[];
  now = storedNow;
  private nextId: number;

  constructor(revisions: RevisionRecord[] = [], summaries: ReportLibraryItem[] = []) {
    this.revisions.push(...revisions);
    this.nextId = Math.max(0, ...revisions.map((record) => record.revision.revisionId)) + 1;
    this.summaries = summaries.map((summary) => ({ ...summary }));
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    const unmodelled: string[] = UNMODELLED_FILTERS.filter((name) => query[name] !== null);
    if (query.sort !== 'newest' && query.sort !== 'oldest') unmodelled.push(`sort ${query.sort}`);
    if (unmodelled.length) throw new Error(`InMemoryIncidentRepository does not model: ${unmodelled.join(', ')}`);
    const direction = query.sort === 'oldest' ? 1 : -1;
    const matching = this.summaries
      .filter((summary) => (query.scope !== 'official' || summary.isOfficial) && (query.kind === null || summary.kind === query.kind))
      .sort((a, b) => direction * (a.generatedAt ?? '').localeCompare(b.generatedAt ?? '') || a.revisionId - b.revisionId);
    // The RPC clamps the page size to 1-1000 and the page to at least 1.
    const size = Math.min(Math.max(query.pageSize, 1), 1000);
    const start = (Math.max(query.page, 1) - 1) * size;
    return {
      items: matching.slice(start, start + size).map((summary) => ({ ...summary })),
      totalItems: matching.length,
      incidentTypes: [...new Set(this.summaries.map((summary) => summary.incident_type))].sort(),
    };
  }

  private ofVideo(videoId: string): RevisionRecord[] {
    return this.revisions.filter((record) => record.revision.videoId === videoId);
  }

  async getRevision(videoId: string, revisionId: number | null): Promise<RevisionRecord | null> {
    const all = this.ofVideo(videoId);
    if (!all.length) return null;
    const official = all[0].video.officialRevisionId;
    const wanted = revisionId ?? official;
    const found = wanted === null
      ? all.reduce((newest, record) => (record.revision.revisionNo > newest.revision.revisionNo ? record : newest))
      : all.find((record) => record.revision.revisionId === wanted);
    if (!found) return null;
    return { ...found, revision: { ...found.revision, isOfficial: official === found.revision.revisionId } };
  }

  async listRevisions(videoId: string): Promise<RevisionSummary[]> {
    const all = this.ofVideo(videoId);
    const official = all[0]?.video.officialRevisionId ?? null;
    return [...all].reverse().map((record) => ({ ...record.revision, isOfficial: official === record.revision.revisionId }));
  }

  async saveHumanRevision(input: HumanRevisionInput): Promise<RevisionSummary> {
    const all = this.ofVideo(input.videoId);
    if (!all.length) throw new StoreRejection('not-found', `Video not found: ${input.videoId}`);
    const parent = all.find((record) => record.revision.revisionId === input.parentId);
    if (!parent) throw new StoreRejection('not-found', `Revision not found for this video: ${input.parentId}`);
    const createdBy = input.createdBy.trim();
    if (!createdBy || createdBy.length > 256) throw new StoreRejection('invalid', 'A reviewer name of 1 to 256 characters is required');
    this.saved.push(input);
    const revision: RevisionSummary = {
      revisionId: this.nextId++,
      videoId: input.videoId,
      revisionNo: Math.max(...all.map((record) => record.revision.revisionNo)) + 1,
      kind: 'human',
      createdBy,
      createdAt: this.now(),
      note: input.note?.trim() || null,
      parentId: input.parentId,
      modelRunId: parent.revision.modelRunId,
      model: parent.revision.model,
      isOfficial: false,
    };
    this.revisions.push({ ...parent, revision, payload: input.payload, evidence: input.evidence, ...structuredFromPayload(input.payload, input.evidence) });
    return revision;
  }
}
