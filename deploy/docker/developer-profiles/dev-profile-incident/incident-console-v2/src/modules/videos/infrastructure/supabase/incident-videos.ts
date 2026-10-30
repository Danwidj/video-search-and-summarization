// SPDX-License-Identifier: Apache-2.0

import { StoreRejection } from '@/modules/shared/domain/common';
import type {
  IncidentVideo,
  IncidentVideoRepository,
  NewIncidentVideo,
  VideoMove,
  VideoRemoval,
} from '@/modules/videos/domain/IncidentVideoRepository';
import type { PostgrestClient } from '@/lib/postgrest/client';

type Row = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const numberOrNull = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const isoOrNull = (value: unknown): string | null => {
  const parsed = typeof value === 'string' ? new Date(value) : null;
  return parsed && !Number.isNaN(parsed.getTime()) ? parsed.toISOString() : null;
};

const COLUMNS = 'id,incident_id,filepath,recorded_at,uploaded_datetime,duration,source';

function incidentVideo(row: Row): IncidentVideo {
  return {
    videoId: String(row.id),
    incidentId: Number(row.incident_id),
    storageKey: text(row.filepath),
    recordedAt: isoOrNull(row.recorded_at),
    uploadedAt: text(row.uploaded_datetime),
    durationSeconds: numberOrNull(row.duration),
    source: text(row.source),
  };
}

/** remove_video RAISEs plain exceptions; its domain refusals become StoreRejection, anything else is rethrown. */
function removalRefusal(error: unknown): never {
  const message = error instanceof Error ? error.message : '';
  const match = /"message":"([^"]+)"/.exec(message);
  if (match && /does not exist/i.test(match[1])) throw new StoreRejection('not-found', match[1]);
  if (match && /last video/i.test(match[1])) throw new StoreRejection('invalid', match[1]);
  throw error;
}

export class SupabaseIncidentVideoAdapter implements IncidentVideoRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async createVideo(input: NewIncidentVideo): Promise<IncidentVideo> {
    if (input.incidentId !== null && !(await this.db.selectOne('incidents', { id: String(input.incidentId) }, 'id')))
      throw new StoreRejection('not-found', `Incident not found: ${input.incidentId}`);
    if (await this.db.selectOne('videos', { id: input.videoId }, 'id'))
      throw new StoreRejection('invalid', `Video name already taken: ${input.videoId}`);
    const incidentId = input.incidentId ?? Number((await this.db.insertRow('incidents', {})).id);
    try {
      const row = await this.db.insertRow('videos', {
        id: input.videoId,
        incident_id: incidentId,
        filepath: input.storageKey,
        recorded_at: input.recordedAt ? new Date(input.recordedAt).toISOString() : null,
        duration: input.durationSeconds == null ? null : Math.round(input.durationSeconds),
        source: input.source ?? null,
      });
      return incidentVideo(row);
    } catch (error) {
      // Do not leave the incident this call started empty behind a failed insert.
      if (input.incidentId === null) await this.db.deleteWhere('incidents', { id: String(incidentId) });
      throw error;
    }
  }

  async getVideo(videoId: string): Promise<IncidentVideo | null> {
    const row = await this.db.selectOne('videos', { id: videoId }, COLUMNS);
    return row ? incidentVideo(row) : null;
  }

  async listVideos(incidentId: number): Promise<IncidentVideo[]> {
    const rows = await this.db.selectMany('videos', {
      filters: { incident_id: String(incidentId) },
      select: COLUMNS,
      order: 'recorded_at.asc.nullslast,id.asc',
    });
    return rows.map(incidentVideo);
  }

  async removeVideo(videoId: string): Promise<VideoRemoval> {
    const result = asRow(await this.db.rpc('remove_video', { p_video_id: videoId, p_mode: 'delete' }).catch(removalRefusal));
    const images = result.deleted_crop_images;
    return {
      videoId,
      incidentId: Number(result.incident_id),
      incidentDeleted: result.incident_deleted === true,
      storageKey: text(result.deleted_video_key),
      cropImages: Array.isArray(images) ? images.filter((image): image is string => typeof image === 'string') : [],
    };
  }

  async moveVideoToNewIncident(videoId: string): Promise<VideoMove> {
    const result = asRow(await this.db.rpc('remove_video', { p_video_id: videoId, p_mode: 'move' }).catch(removalRefusal));
    return { videoId, incidentId: Number(result.incident_id), newIncidentId: Number(result.new_incident_id) };
  }
}
