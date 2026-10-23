// SPDX-License-Identifier: Apache-2.0

// In-memory VideoRepository for use-case tests. It mirrors the rules the
// database enforces through set_official_revision (only a revision of the
// video can be official; null clears it) and the list filters.

import {
  StoreRejection,
  type OfficialChange, type Page, type VideoListFilter, type VideoListItem, type VideoRecord, type VideoRepository,
} from '@/lib/ports';
import type { OfficialCrop } from '@/lib/reports/revision';

export interface InMemoryVideo extends VideoRecord {
  /** Ids of this video's report revisions. */
  revisionIds: number[];
}

export class InMemoryVideoRepository implements VideoRepository {
  readonly videos = new Map<string, InMemoryVideo>();
  /** Each setOfficialRevision call, for tests to assert on the crops passed. */
  readonly officialCalls: Array<{ videoId: string; revisionId: number | null; crops: OfficialCrop[] }> = [];

  constructor(videos: InMemoryVideo[] = []) {
    for (const video of videos) this.videos.set(video.videoId, { ...video, revisionIds: [...video.revisionIds] });
  }

  async listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>> {
    const all = [...this.videos.values()]
      .filter((video) => filter === 'all'
        || (filter === 'without-report' && video.revisionIds.length === 0)
        || (filter === 'awaiting-selection' && video.revisionIds.length > 0 && video.officialRevisionId === null))
      .sort((a, b) => (a.uploadedAt === b.uploadedAt ? a.videoId.localeCompare(b.videoId)
        : a.uploadedAt === null ? 1 : b.uploadedAt === null ? -1 : b.uploadedAt.localeCompare(a.uploadedAt)));
    const items = all.slice((page - 1) * pageSize, page * pageSize).map((video) => ({
      videoId: video.videoId,
      filename: (video.storageKey ?? '').split('/').pop() || video.videoId,
      uploadedAt: video.uploadedAt,
      source: video.source,
      revisions: video.revisionIds.length,
      officialRevisionId: video.officialRevisionId,
    }));
    return { items, totalItems: all.length };
  }

  async getVideo(videoId: string): Promise<VideoRecord | null> {
    const video = this.videos.get(videoId);
    if (!video) return null;
    const { revisionIds: _ids, ...record } = video;
    return record;
  }

  async setOfficialRevision(videoId: string, revisionId: number | null, crops: OfficialCrop[]): Promise<OfficialChange> {
    const video = this.videos.get(videoId);
    if (!video) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
    if (revisionId !== null && !video.revisionIds.includes(revisionId)) throw new StoreRejection('not-found', `Revision not found for this video: ${revisionId}`);
    this.officialCalls.push({ videoId, revisionId, crops });
    video.officialRevisionId = revisionId;
    return { videoId, officialRevisionId: revisionId, crops: revisionId === null ? 0 : crops.length };
  }

  async deleteVideo(videoId: string): Promise<void> {
    this.videos.delete(videoId);
  }
}
