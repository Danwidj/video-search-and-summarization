// SPDX-License-Identifier: Apache-2.0

// Shared by the incident write routes: the incident's own video by name.

import type { IncidentVideoRepository } from '@/modules/videos/domain/IncidentVideoRepository';

/** getVideo that only finds videos of this incident, so a video of another incident answers "not found". */
export function incidentVideoLookup(videos: Pick<IncidentVideoRepository, 'getVideo'>, incidentId: number) {
  return {
    async getVideo(videoId: string) {
      const video = await videos.getVideo(videoId);
      return video && video.incidentId === incidentId ? { storageKey: video.storageKey } : null;
    },
  };
}
