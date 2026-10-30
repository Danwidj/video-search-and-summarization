// SPDX-License-Identifier: Apache-2.0

// Shared by the incident write routes: the incident id from the path and the incident's own video by name.

import type { IncidentVideoRepository } from '@/modules/videos/domain/IncidentVideoRepository';

/** A positive integer incident id from a path segment; null for anything else. */
export function parseIncidentId(raw: string): number | null {
  return /^[1-9]\d{0,14}$/.test(raw) ? Number(raw) : null;
}

/** getVideo that only finds videos of this incident, so a video of another incident answers "not found". */
export function incidentVideoLookup(videos: Pick<IncidentVideoRepository, 'getVideo'>, incidentId: number) {
  return {
    async getVideo(videoId: string) {
      const video = await videos.getVideo(videoId);
      return video && video.incidentId === incidentId ? { storageKey: video.storageKey } : null;
    },
  };
}
