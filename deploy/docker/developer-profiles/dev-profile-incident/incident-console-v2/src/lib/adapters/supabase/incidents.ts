// SPDX-License-Identifier: Apache-2.0

import {
  REVISION_SUMMARY_COLUMNS, revisionRecordFromRows, revisionSummaryFromRow, savedRevisionFromRpc,
} from '@/lib/adapters/supabase/mappers/report';
import { reportListFromRpc, reportListRpcArgs } from '@/lib/adapters/supabase/mappers/report-library';
import { StoreRejection } from '@/modules/shared/domain/common';
import {
  type HumanRevisionInput, type IncidentRepository, type ReportList, type ReportListQuery, type RevisionRecord,
} from '@/lib/ports/incidents';
import type { PostgrestClient } from '@/lib/postgrest/client';
import { revisionFacets, type RevisionSummary } from '@/lib/reports/revision';

type Row = Record<string, unknown>;

/**
 * save_human_revision RAISEs (SQLSTATE P0001) to refuse a request for a domain reason: an unknown
 * video or parent, an empty reviewer name, a malformed payload. Those become StoreRejection;
 * anything else is rethrown unchanged.
 */
function reviewerRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  if (!/"code":"P0001"/.test(message)) throw error;
  const match = /"message":"((?:[^"\\]|\\.)*)"/.exec(message);
  const reason = match ? (JSON.parse(`"${match[1]}"`) as string) : 'The database refused the request';
  throw new StoreRejection(/not found/i.test(reason) ? 'not-found' : 'invalid', reason);
}

const officialId = (video: Row): number | null => (typeof video.official_revision_id === 'number' ? video.official_revision_id : null);

export class SupabaseIncidentAdapter implements IncidentRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    return reportListFromRpc(await this.db.rpc('list_incident_report_summaries', reportListRpcArgs(query)));
  }

  async getRevision(videoId: string, revisionId: number | null): Promise<RevisionRecord | null> {
    const video = await this.db.selectOne('videos', { id: videoId });
    if (!video) return null;
    const wanted = revisionId ?? officialId(video);
    const revision = wanted !== null
      ? await this.db.selectOne('report_revisions', { video_id: videoId, id: String(wanted) })
      : (await this.db.selectMany('report_revisions', { filters: { video_id: videoId }, order: 'revision_no.desc', limit: 1 }))[0] ?? null;
    if (!revision) return null;
    const runId = typeof revision.model_run_id === 'string' ? revision.model_run_id : null;
    const modelRun = runId ? await this.db.selectOne('model_runs', { id: runId }) : null;
    return revisionRecordFromRows({ video, revision, modelRun });
  }

  async listRevisions(videoId: string): Promise<RevisionSummary[]> {
    const video = await this.db.selectOne('videos', { id: videoId }, 'id,official_revision_id');
    if (!video) return [];
    const revisions = await this.db.selectMany('report_revisions', { filters: { video_id: videoId }, select: REVISION_SUMMARY_COLUMNS, order: 'revision_no.desc' });
    const runIds = [...new Set(revisions.flatMap((row) => (typeof row.model_run_id === 'string' ? [row.model_run_id] : [])))];
    const runs = runIds.length ? await this.db.selectIn('model_runs', 'id', runIds, 'id,model_name') : [];
    const models = new Map(runs.map((run) => [String(run.id), typeof run.model_name === 'string' ? run.model_name : null]));
    return revisions.map((row) => revisionSummaryFromRow(row, officialId(video), models.get(String(row.model_run_id)) ?? null));
  }

  async saveHumanRevision(input: HumanRevisionInput): Promise<RevisionSummary> {
    const facets = revisionFacets(input.payload);
    const result = await this.db.rpc('save_human_revision', {
      p_video_id: input.videoId,
      p_parent_id: input.parentId,
      p_created_by: input.createdBy,
      p_note: input.note,
      p_payload: input.payload,
      p_evidence: input.evidence,
      p_incident_type: facets.incident_type,
      p_severity_level: facets.severity_level,
      p_start_seconds: facets.start_seconds,
      p_end_seconds: facets.end_seconds,
    }).catch(reviewerRefusal);
    return savedRevisionFromRpc(result);
  }
}
