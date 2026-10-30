// SPDX-License-Identifier: Apache-2.0

// VideoAnalysisRepository over PostgREST (table video_analyses). Rows are only
// ever inserted; the latest per video is the newest created_at, then highest id.

import type { PostgrestClient } from '@/lib/postgrest/client';
import type { NewVideoAnalysis, VideoAnalysis, VideoAnalysisRepository } from '@/modules/analysis/domain/VideoAnalysisRepository';
import { evidenceEntries, revisionFacets, type ReportPayload } from '@/modules/reports/domain/revision';

// Every column except the embedding, which is large and only searched in the database.
const COLUMNS = 'id,video_id,model_run_id,payload,evidence,incident_type,severity_level,start_seconds,end_seconds,created_at';
const NEWEST_FIRST = 'created_at.desc,id.desc';

const numberOrNull = (value: unknown): number | null => (typeof value === 'number' ? value : null);

function analysisFromRow(row: Record<string, unknown>): VideoAnalysis {
  return {
    id: Number(row.id),
    videoId: String(row.video_id),
    modelRunId: String(row.model_run_id),
    payload: (row.payload ?? {}) as ReportPayload,
    evidence: evidenceEntries(row.evidence),
    incidentType: typeof row.incident_type === 'string' ? row.incident_type : null,
    severityLevel: numberOrNull(row.severity_level),
    startSeconds: numberOrNull(row.start_seconds),
    endSeconds: numberOrNull(row.end_seconds),
    createdAt: String(row.created_at ?? ''),
  };
}

export class SupabaseVideoAnalysisAdapter implements VideoAnalysisRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async saveAnalysis(analysis: NewVideoAnalysis): Promise<VideoAnalysis> {
    const row = await this.db.insertRow('video_analyses', {
      video_id: analysis.videoId,
      model_run_id: analysis.modelRunId,
      payload: analysis.payload,
      evidence: analysis.evidence,
      ...revisionFacets(analysis.payload),
      embedding: analysis.embedding ?? null,
      ...(analysis.createdAt ? { created_at: analysis.createdAt } : {}),
    });
    return analysisFromRow(row);
  }

  async latestAnalysis(videoId: string): Promise<VideoAnalysis | null> {
    const [row] = await this.db.selectMany('video_analyses', {
      filters: { video_id: videoId },
      select: COLUMNS,
      order: NEWEST_FIRST,
      limit: 1,
    });
    return row ? analysisFromRow(row) : null;
  }

  async latestAnalyses(videoIds: string[]): Promise<Map<string, VideoAnalysis>> {
    const latest = new Map<string, VideoAnalysis>();
    if (videoIds.length === 0) return latest;
    const rows = await this.db.selectIn('video_analyses', 'video_id', videoIds, COLUMNS);
    for (const row of rows.map(analysisFromRow)) {
      const current = latest.get(row.videoId);
      if (!current || row.createdAt > current.createdAt || (row.createdAt === current.createdAt && row.id > current.id)) {
        latest.set(row.videoId, row);
      }
    }
    return latest;
  }

  async listAnalyses(videoId: string): Promise<VideoAnalysis[]> {
    const rows = await this.db.selectMany('video_analyses', {
      filters: { video_id: videoId },
      select: COLUMNS,
      order: 'created_at.asc,id.asc',
    });
    return rows.map(analysisFromRow);
  }
}
