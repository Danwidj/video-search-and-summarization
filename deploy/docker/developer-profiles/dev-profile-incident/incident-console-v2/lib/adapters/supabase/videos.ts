// SPDX-License-Identifier: Apache-2.0

import {
  StoreRejection,
  type OfficialChange, type Page, type VideoListFilter, type VideoListItem, type VideoRecord, type VideoRepository,
} from '@/lib/ports';
import type { OfficialCrop } from '@/lib/reports/revision';
import type { PostgrestClient } from '@/lib/postgrest/client';
import { explicitVideoId } from '@/lib/reports/run-notes';

type Row = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});

/**
 * set_official_revision RAISEs plain exceptions; its domain refusals become StoreRejection,
 * anything else is rethrown unchanged.
 */
function officialRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  const match = /"message":"([^"]+)"/.exec(message);
  if (match && /not found|embedding/i.test(match[1])) {
    throw new StoreRejection(/not found/i.test(match[1]) ? 'not-found' : 'invalid', match[1]);
  }
  throw error;
}

function videoListItem(row: Row): VideoListItem {
  const revisions = Array.isArray(row.report_revisions) ? row.report_revisions : [];
  const filepath = typeof row.filepath === 'string' ? row.filepath : '';
  return {
    videoId: String(row.id),
    filename: filepath.split('/').pop() || String(row.id),
    uploadedAt: text(row.uploaded_datetime),
    source: text(row.source),
    revisions: revisions.length,
    officialRevisionId: numberOrNull(row.official_revision_id),
  };
}

export class SupabaseVideoAdapter implements VideoRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>> {
    // videos and report_revisions are linked by two foreign keys (a revision -> its video, and
    // a video -> its official revision), so every embed names the revision -> video one.
    const base = 'id,filepath,uploaded_datetime,source,official_revision_id';
    const embed = 'report_revisions!report_revisions_video_id_fkey';
    const query: Record<string, string> = {
      select: filter === 'without-report' ? `${base},${embed}(id)`
        // Awaiting selection: at least one revision, and none marked official.
        : filter === 'awaiting-selection' ? `${base},${embed}!inner(id)`
          : `${base},${embed}(id)`,
      order: 'uploaded_datetime.desc.nullslast,id.asc',
    };
    if (filter === 'without-report') query.report_revisions = 'is.null';
    if (filter === 'awaiting-selection') query.official_revision_id = 'is.null';
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
      officialRevisionId: numberOrNull(row.official_revision_id),
    };
  }

  async setOfficialRevision(videoId: string, revisionId: number | null, crops: OfficialCrop[]): Promise<OfficialChange> {
    const result = asRow(await this.db.rpc('set_official_revision', {
      p_video_id: videoId,
      p_revision_id: revisionId,
      p_crops: crops,
    }).catch(officialRefusal));
    // The RPC returns exactly these keys (the sibling's supabase/functions-final.sql).
    return {
      videoId: text(result.videoId) ?? videoId,
      officialRevisionId: numberOrNull(result.officialRevisionId),
      crops: numberOrNull(result.crops) ?? 0,
    };
  }

  async deleteVideo(videoId: string): Promise<void> {
    await this.db.deleteWhere('videos', { id: videoId });
    // revisions, evidence crops and query results cascade from the video. Then remove the run
    // records whose parsed notes name exactly this video and that no revision uses any more; the
    // notes text match is only a pre-filter.
    const candidates = await this.db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,notes');
    for (const candidate of candidates) {
      if (typeof candidate.id !== 'string' || explicitVideoId(candidate.notes) !== videoId) continue;
      if (await this.db.selectOne('report_revisions', { model_run_id: candidate.id }, 'id')) continue;
      await this.db.deleteWhere('model_runs', { id: candidate.id });
    }
  }
}
