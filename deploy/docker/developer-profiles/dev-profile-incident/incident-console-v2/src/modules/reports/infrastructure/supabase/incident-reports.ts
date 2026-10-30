// SPDX-License-Identifier: Apache-2.0

import type { PostgrestClient } from '@/lib/postgrest/client';
import type { ReportListQuery } from '@/modules/reports/domain/IncidentRepository';
import type {
  AutoJoinInput,
  AiIncidentRevisionInput,
  CreatedAiRevision,
  HumanIncidentRevisionInput,
  IncidentId,
  IncidentCrop,
  IncidentOfficialChange,
  IncidentRecord,
  IncidentReportRepository,
  IncidentRevisionRecord,
  IncidentRevisionSummary,
  IncidentSideSummary,
  IncidentSummaryList,
  MergeResult,
} from '@/modules/reports/domain/IncidentReportRepository';
import { evidenceFolder } from '@/modules/reports/domain/revision';
import { reportListRpcArgs } from '@/modules/reports/infrastructure/supabase/mappers/report-library';
import {
  createdAiRevisionFromRpc,
  envelopeFacets,
  INCIDENT_REVISION_SUMMARY_COLUMNS,
  incidentRecordFromRows,
  incidentRefusal,
  incidentRevisionRecordFromRows,
  incidentSideSummaryFromRows,
  incidentSummaryListFromRpc,
  mergeResultFromRpc,
  officialChangeFromRpc,
  REVISION_TITLE_COLUMNS,
  SIDE_VIDEO_COLUMNS,
  savedIncidentRevisionFromRpc,
} from '@/modules/reports/infrastructure/supabase/mappers/incident-reports';

type Row = Record<string, unknown>;

/** PostgREST answers at most this many rows to a request without a range; an answer that long may be cut short. */
const POSTGREST_MAX_ROWS = 1000;

/** Every string anywhere in a stored JSON value, so a key under a field this console does not know is still seen. */
function stringsIn(value: unknown, into: Set<string>): void {
  if (typeof value === 'string') {
    into.add(value);
  } else if (Array.isArray(value)) {
    for (const item of value) stringsIn(item, into);
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) stringsIn(item, into);
  }
}

const id = (value: number): string => String(value);

/** The SQL casts a crop's embedding to vector(1024), which refuses an empty list; a crop with none sends null. */
const cropRows = (crops: IncidentCrop[]): Array<Record<string, unknown>> =>
  crops.map((crop) => ({ ...crop, embedding: crop.embedding.length ? crop.embedding : null }));

/** pgvector takes its text form, `[1,2,3]`. */
const vectorText = (embedding: number[] | null): string | null => (embedding ? `[${embedding.join(',')}]` : null);

export class SupabaseIncidentReportAdapter implements IncidentReportRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listIncidents(query: ReportListQuery): Promise<IncidentSummaryList> {
    return incidentSummaryListFromRpc(await this.db.rpc('list_incident_report_summaries', reportListRpcArgs(query)));
  }

  async getIncident(incidentId: IncidentId): Promise<IncidentRecord | null> {
    const incident = await this.db.selectOne('incidents', { id: id(incidentId) });
    if (!incident) return null;
    const [videos, revisions] = await Promise.all([
      this.db.selectMany('videos', { filters: { incident_id: id(incidentId) } }),
      this.db.selectMany('report_revisions', {
        filters: { incident_id: id(incidentId) },
        select: INCIDENT_REVISION_SUMMARY_COLUMNS,
        order: 'revision_no.desc',
      }),
    ]);
    if (revisions.length >= POSTGREST_MAX_ROWS) throw new Error(`Too many revisions to list incident ${incidentId} in one request`);
    const runIds = [...new Set(revisions.flatMap((row) => (typeof row.model_run_id === 'string' ? [row.model_run_id] : [])))];
    const runs = runIds.length ? await this.db.selectIn('model_runs', 'id', runIds, 'id,model_name') : [];
    const models = new Map(runs.map((run) => [String(run.id), typeof run.model_name === 'string' ? run.model_name : null]));
    return incidentRecordFromRows(incident, videos, revisions, models);
  }

  /** Two round trips at most: the incident, its videos and its newest title together, then the official title when that is another revision. */
  async getSideSummary(incidentId: IncidentId): Promise<IncidentSideSummary | null> {
    const [incident, videos, [newest = null]] = await Promise.all([
      this.db.selectOne('incidents', { id: id(incidentId) }, 'id,official_revision_id'),
      this.db.selectMany('videos', { filters: { incident_id: id(incidentId) }, select: SIDE_VIDEO_COLUMNS }),
      this.db.selectMany('report_revisions', {
        filters: { incident_id: id(incidentId) },
        select: REVISION_TITLE_COLUMNS,
        order: 'revision_no.desc',
        limit: 1,
      }),
    ]);
    if (!incident) return null;
    const officialId = typeof incident.official_revision_id === 'number' ? incident.official_revision_id : null;
    const shown =
      officialId === null || officialId === Number(newest?.id)
        ? newest
        : await this.db.selectOne('report_revisions', { incident_id: id(incidentId), id: id(officialId) }, REVISION_TITLE_COLUMNS);
    return incidentSideSummaryFromRows(incident, videos, shown);
  }

  async getRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentRevisionRecord | null> {
    const incident = await this.db.selectOne('incidents', { id: id(incidentId) });
    if (!incident) return null;
    const wanted = revisionId ?? (typeof incident.official_revision_id === 'number' ? incident.official_revision_id : null);
    const revision =
      wanted !== null
        ? await this.db.selectOne('report_revisions', { incident_id: id(incidentId), id: id(wanted) })
        : ((
            await this.db.selectMany('report_revisions', { filters: { incident_id: id(incidentId) }, order: 'revision_no.desc', limit: 1 })
          )[0] ?? null);
    if (!revision) return null;
    const runId = typeof revision.model_run_id === 'string' ? revision.model_run_id : null;
    const modelRun = runId ? await this.db.selectOne('model_runs', { id: runId }) : null;
    return incidentRevisionRecordFromRows({ incident, revision, modelRun });
  }

  async setOfficialRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentOfficialChange> {
    const result = await this.db
      .rpc('set_official_revision', { p_incident_id: incidentId, p_revision_id: revisionId })
      .catch(incidentRefusal);
    return officialChangeFromRpc(result);
  }

  async saveHumanRevision(input: HumanIncidentRevisionInput): Promise<IncidentRevisionSummary> {
    const facets = envelopeFacets(input.payload);
    const result = await this.db
      .rpc('save_human_revision_with_crops', {
        p_incident_id: input.incidentId,
        p_parent_id: input.parentId,
        p_created_by: input.createdBy,
        p_note: input.note,
        p_payload: input.payload,
        p_evidence: input.evidence,
        p_incident_type: facets.incident_type,
        p_severity_level: facets.severity_level,
        p_start_seconds: facets.start_seconds,
        p_end_seconds: facets.end_seconds,
        p_crops: cropRows(input.crops),
      })
      .catch(incidentRefusal);
    return savedIncidentRevisionFromRpc(result);
  }

  async createAiRevision(input: AiIncidentRevisionInput): Promise<CreatedAiRevision> {
    const facets = envelopeFacets(input.payload);
    const result = await this.db
      .rpc('create_ai_revision', {
        p_incident_id: input.incidentId,
        p_model_run_id: input.modelRunId,
        p_note: input.note,
        p_payload: input.payload,
        p_evidence: input.evidence,
        p_video_names: input.videoNames,
        p_incident_type: facets.incident_type,
        p_severity_level: facets.severity_level,
        p_start_seconds: facets.start_seconds,
        p_end_seconds: facets.end_seconds,
        p_embedding: vectorText(input.embedding),
      })
      .catch(incidentRefusal);
    return createdAiRevisionFromRpc(result);
  }

  async setRevisionCrops(incidentId: IncidentId, revisionId: number, crops: IncidentCrop[]): Promise<number> {
    const result = await this.db
      .rpc('set_revision_crops', { p_incident_id: incidentId, p_revision_id: revisionId, p_crops: cropRows(crops) })
      .catch(incidentRefusal);
    return Number((result as Row | null)?.crops ?? 0);
  }

  async replaceVideoCrops(incidentId: IncidentId, videoId: string, revisionId: number | null, crops: IncidentCrop[]): Promise<number> {
    const result = await this.db
      .rpc('replace_video_crops', { p_incident_id: incidentId, p_video_id: videoId, p_revision_id: revisionId, p_crops: cropRows(crops) })
      .catch(incidentRefusal);
    return typeof result === 'number' ? result : 0;
  }

  async listReferencedEvidenceImages(incidentId: IncidentId, videoId: string): Promise<string[] | null> {
    const video = await this.db.selectOne('videos', { id: videoId, incident_id: id(incidentId) }, 'id,filepath');
    if (!video) return null;
    const [revisions, crops] = await Promise.all([
      this.db.selectMany('report_revisions', { filters: { incident_id: id(incidentId) }, select: 'id,evidence' }),
      this.db.selectMany('evidence_crops', { filters: { video_id: videoId }, select: 'image' }),
    ]);
    if (revisions.length >= POSTGREST_MAX_ROWS || crops.length >= POSTGREST_MAX_ROWS) {
      throw new Error(`Too many records to list the references of ${videoId} in one request`);
    }
    const keys = new Set<string>();
    const folder = typeof video.filepath === 'string' && video.filepath ? evidenceFolder(video.filepath) : null;
    if (folder) {
      for (const row of revisions) {
        if (row.evidence !== null && !Array.isArray(row.evidence)) {
          throw new Error(`Revision ${String(row.id)} has evidence that is not a list`);
        }
        const found = new Set<string>();
        stringsIn(row.evidence, found);
        for (const key of found) if (key.startsWith(folder)) keys.add(key);
      }
    }
    for (const row of crops) if (typeof row.image === 'string') keys.add(row.image);
    return [...keys].filter((key) => key.startsWith('evidence/'));
  }

  async mergeIncidents(targetIncidentId: IncidentId, sourceIncidentId: IncidentId, autoJoin?: AutoJoinInput): Promise<MergeResult> {
    const ids = { p_target_incident_id: targetIncidentId, p_source_incident_id: sourceIncidentId };
    const result = await (autoJoin
      ? this.db.rpc('auto_merge_incidents', { ...ids, p_score: autoJoin.score, p_reasons: autoJoin.reasons })
      : this.db.rpc('merge_incidents', ids)
    ).catch(incidentRefusal);
    return mergeResultFromRpc(result);
  }
}
