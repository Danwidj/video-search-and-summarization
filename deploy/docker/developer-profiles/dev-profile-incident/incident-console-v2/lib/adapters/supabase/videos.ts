// SPDX-License-Identifier: Apache-2.0

import {
  StoreRejection,
  type OfficialClearance, type OfficialSelection, type Page, type VideoListFilter, type VideoListItem, type VideoRecord, type VideoRepository,
} from '@/lib/ports';
import type { PostgrestClient } from '@/lib/postgrest/client';
import { explicitVideoId } from '@/lib/reports/run-notes';

type Row = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});

/**
 * select_official_report / clear_official_report RAISE plain exceptions; their
 * domain refusals become StoreRejection, anything else is rethrown unchanged.
 */
function officialRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  const match = /"message":"([^"]+)"/.exec(message);
  if (match && /official report|reviewer name|Video not found/.test(match[1])) {
    throw new StoreRejection(/Video not found/.test(match[1]) ? 'not-found' : 'invalid', match[1]);
  }
  throw error;
}

function videoListItem(row: Row): VideoListItem {
  const incidents = Array.isArray(row.incidents) ? (row.incidents as Row[]) : [];
  const filepath = typeof row.filepath === 'string' ? row.filepath : '';
  return {
    videoId: String(row.id),
    filename: filepath.split('/').pop() || String(row.id),
    uploadedAt: text(row.uploaded_datetime),
    source: text(row.source),
    analysesWithReport: incidents.filter((incident) => Array.isArray(incident.reports) && incident.reports.length > 0).length,
    officialRunId: text(row.selected_model_run_id),
  };
}

export class SupabaseVideoAdapter implements VideoRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>> {
    // videos and incidents are linked by two foreign keys (incident -> its video,
    // and video -> its official run), so every embed names the incident -> video one.
    const base = 'id,filepath,uploaded_datetime,source,selected_model_run_id';
    const query: Record<string, string> = {
      select: filter === 'without-report' ? `${base},incidents!incidents_incident_id_fkey(model_run_id)`
        // Awaiting selection: at least one analysis with a report, and no official report chosen.
        : filter === 'awaiting-selection' ? `${base},incidents!incidents_incident_id_fkey!inner(model_run_id,reports!inner(id))`
          : `${base},incidents!incidents_incident_id_fkey(model_run_id,reports(id))`,
      order: 'uploaded_datetime.desc.nullslast,id.asc',
    };
    if (filter === 'without-report') query.incidents = 'is.null';
    if (filter === 'awaiting-selection') query.selected_model_run_id = 'is.null';
    const { rows, total } = await this.db.selectPage('videos', query, pageSize, (page - 1) * pageSize);
    return { items: rows.map(videoListItem), totalItems: total };
  }

  async getVideo(videoId: string): Promise<VideoRecord | null> {
    const row = await this.db.selectOne('videos', { id: videoId });
    if (!row) return null;
    return {
      videoId,
      storageKey: text(row.filepath),
      uploadedAt: text(row.uploaded_datetime),
      source: text(row.source),
      officialRunId: text(row.selected_model_run_id),
    };
  }

  async selectOfficialRun(videoId: string, modelRunId: string, selectedBy: string): Promise<OfficialSelection> {
    const result = asRow(await this.db.rpc('select_official_report', { p_video_id: videoId, p_model_run_id: modelRunId, p_selected_by: selectedBy }).catch(officialRefusal));
    // The RPC returns exactly these keys (20260927170000_official_report_selection.sql).
    return {
      videoId: text(result.videoId) ?? videoId,
      officialRunId: text(result.officialRunId) ?? modelRunId,
      selectedBy: text(result.selectedBy) ?? selectedBy.trim(),
      selectedAt: text(result.selectedAt) ?? '',
    };
  }

  async clearOfficialRun(videoId: string, clearedBy: string): Promise<OfficialClearance> {
    const result = asRow(await this.db.rpc('clear_official_report', { p_video_id: videoId, p_cleared_by: clearedBy }).catch(officialRefusal));
    return { videoId: text(result.videoId) ?? videoId, officialRunId: null, clearedBy: text(result.clearedBy) ?? clearedBy.trim() };
  }

  async deleteVideo(videoId: string): Promise<void> {
    await this.db.deleteWhere('videos', { id: videoId });
    // incidents, evidence, review status and reports cascade from the video. Then
    // remove the run records whose parsed notes name exactly this video and that
    // have no incident left; the notes text match is only a pre-filter.
    const candidates = await this.db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,notes');
    for (const candidate of candidates) {
      if (typeof candidate.id !== 'string' || explicitVideoId(candidate.notes) !== videoId) continue;
      if (await this.db.selectOne('incidents', { model_run_id: candidate.id }, 'incident_id')) continue;
      await this.db.deleteWhere('model_runs', { id: candidate.id });
    }
  }
}
