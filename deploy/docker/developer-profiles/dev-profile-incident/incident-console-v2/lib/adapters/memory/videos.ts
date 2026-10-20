// SPDX-License-Identifier: Apache-2.0

// In-memory VideoRepository for use-case tests. It mirrors the rules the
// database enforces through the official-report RPCs (only a run with a report
// can be official; a reviewer name is required) and the list filters.

import {
  StoreRejection,
  type OfficialClearance, type OfficialSelection, type Page, type VideoListFilter, type VideoListItem, type VideoRecord, type VideoRepository,
} from '@/lib/ports';

export interface InMemoryVideo extends VideoRecord {
  /** Runs of this video that have an incident and a report. */
  runsWithReport: string[];
}

const ONLY_REPORTED_RUNS = 'Only a successful analysis of this video that has a report can be the official report';

export class InMemoryVideoRepository implements VideoRepository {
  readonly videos = new Map<string, InMemoryVideo>();

  constructor(videos: InMemoryVideo[] = []) {
    for (const video of videos) this.videos.set(video.videoId, { ...video, runsWithReport: [...video.runsWithReport] });
  }

  async listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>> {
    const all = [...this.videos.values()]
      .filter((video) => filter === 'all'
        || (filter === 'without-report' && video.runsWithReport.length === 0)
        || (filter === 'awaiting-selection' && video.runsWithReport.length > 0 && !video.officialRunId))
      .sort((a, b) => (a.uploadedAt === b.uploadedAt ? a.videoId.localeCompare(b.videoId)
        : a.uploadedAt === null ? 1 : b.uploadedAt === null ? -1 : b.uploadedAt.localeCompare(a.uploadedAt)));
    const items = all.slice((page - 1) * pageSize, page * pageSize).map((video) => ({
      videoId: video.videoId,
      filename: (video.storageKey ?? '').split('/').pop() || video.videoId,
      uploadedAt: video.uploadedAt,
      source: video.source,
      analysesWithReport: video.runsWithReport.length,
      officialRunId: video.officialRunId,
    }));
    return { items, totalItems: all.length };
  }

  async getVideo(videoId: string): Promise<VideoRecord | null> {
    const video = this.videos.get(videoId);
    if (!video) return null;
    const { runsWithReport: _runs, ...record } = video;
    return record;
  }

  async selectOfficialRun(videoId: string, modelRunId: string, selectedBy: string): Promise<OfficialSelection> {
    if (!selectedBy.trim()) throw new StoreRejection('invalid', 'A reviewer name is required');
    const video = this.videos.get(videoId);
    if (!video) throw new StoreRejection('not-found', 'Video not found');
    if (!video.runsWithReport.includes(modelRunId)) throw new StoreRejection('invalid', ONLY_REPORTED_RUNS);
    video.officialRunId = modelRunId;
    return { videoId, officialRunId: modelRunId, selectedBy: selectedBy.trim(), selectedAt: new Date().toISOString().replace('Z', '') };
  }

  async clearOfficialRun(videoId: string, clearedBy: string): Promise<OfficialClearance> {
    if (!clearedBy.trim()) throw new StoreRejection('invalid', 'A reviewer name is required');
    const video = this.videos.get(videoId);
    if (!video) throw new StoreRejection('not-found', 'Video not found');
    video.officialRunId = null;
    return { videoId, officialRunId: null, clearedBy: clearedBy.trim() };
  }

  async deleteVideo(videoId: string): Promise<void> {
    this.videos.delete(videoId);
  }
}
