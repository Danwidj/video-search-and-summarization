// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentVideoRepository for use-case tests. It mirrors the rules the database
// enforces: a name is unique, a video joins an existing incident or starts one, the last video's
// removal takes the incident with it, and moving the last video is refused (remove_video).

import { StoreRejection } from '@/modules/shared/domain/common';
import type {
  IncidentVideo,
  IncidentVideoRepository,
  NewIncidentVideo,
  VideoMove,
  VideoRemoval,
} from '@/modules/videos/domain/IncidentVideoRepository';

export class InMemoryIncidentVideoRepository implements IncidentVideoRepository {
  readonly videos = new Map<string, IncidentVideo>();
  private readonly incidents = new Set<number>();
  private nextIncidentId = 1;

  private readonly now: () => Date;

  constructor(videos: IncidentVideo[] = [], now: () => Date = () => new Date()) {
    this.now = now;
    for (const video of videos) {
      this.videos.set(video.videoId, { ...video });
      this.incidents.add(video.incidentId);
      this.nextIncidentId = Math.max(this.nextIncidentId, video.incidentId + 1);
    }
  }

  private newIncident(): number {
    const id = this.nextIncidentId++;
    this.incidents.add(id);
    return id;
  }

  private inIncident(incidentId: number): IncidentVideo[] {
    return [...this.videos.values()].filter((video) => video.incidentId === incidentId);
  }

  async createVideo(input: NewIncidentVideo): Promise<IncidentVideo> {
    if (input.incidentId !== null && !this.incidents.has(input.incidentId))
      throw new StoreRejection('not-found', `Incident not found: ${input.incidentId}`);
    if (this.videos.has(input.videoId)) throw new StoreRejection('invalid', `Video name already taken: ${input.videoId}`);
    const video: IncidentVideo = {
      videoId: input.videoId,
      incidentId: input.incidentId ?? this.newIncident(),
      storageKey: input.storageKey,
      recordedAt: input.recordedAt ? new Date(input.recordedAt).toISOString() : null,
      uploadedAt: this.now().toISOString(),
      durationSeconds: input.durationSeconds == null ? null : Math.round(input.durationSeconds),
      source: input.source ?? null,
    };
    this.videos.set(video.videoId, video);
    return { ...video };
  }

  async getVideo(videoId: string): Promise<IncidentVideo | null> {
    const video = this.videos.get(videoId);
    return video ? { ...video } : null;
  }

  async listVideos(incidentId: number): Promise<IncidentVideo[]> {
    return this.inIncident(incidentId)
      .sort((a, b) =>
        a.recordedAt === b.recordedAt
          ? a.videoId.localeCompare(b.videoId)
          : a.recordedAt === null
            ? 1
            : b.recordedAt === null
              ? -1
              : a.recordedAt.localeCompare(b.recordedAt),
      )
      .map((video) => ({ ...video }));
  }

  async removeVideo(videoId: string): Promise<VideoRemoval> {
    const video = this.videos.get(videoId);
    if (!video) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
    const incidentDeleted = this.inIncident(video.incidentId).length < 2;
    this.videos.delete(videoId);
    if (incidentDeleted) this.incidents.delete(video.incidentId);
    return { videoId, incidentId: video.incidentId, incidentDeleted, storageKey: video.storageKey, cropImages: [] };
  }

  async moveVideoToNewIncident(videoId: string): Promise<VideoMove> {
    const video = this.videos.get(videoId);
    if (!video) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
    if (this.inIncident(video.incidentId).length < 2)
      throw new StoreRejection('invalid', `Video ${videoId} is the last video of its incident; delete it instead of moving it`);
    const incidentId = video.incidentId;
    video.incidentId = this.newIncident();
    return { videoId, incidentId, newIncidentId: video.incidentId };
  }
}
