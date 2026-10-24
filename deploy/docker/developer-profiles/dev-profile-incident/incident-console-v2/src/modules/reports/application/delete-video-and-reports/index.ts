// SPDX-License-Identifier: Apache-2.0

// Delete video and reports: removes a whole video, its stored objects first.

import type { VideoRepository } from '@/modules/videos/domain/VideoRepository';
import type { RemoveStoredVideo } from '@/modules/reports/application/types';

/**
 * Deletes the whole video: its stored objects first, then the video row
 * (revisions, evidence crops and query results cascade) and the run records
 * that name only this video. Revisions are append-only, so there is no
 * deleting a single one. Evidence images under evidence/<videoId>/ are left in R2.
 */
export async function deleteVideoAndReports(videos: VideoRepository, videoId: string, removeStoredVideo: RemoveStoredVideo): Promise<void> {
  const video = await videos.getVideo(videoId);
  if (video?.storageKey == null) throw new Error('Video has no R2 object key');
  await removeStoredVideo(video.storageKey);
  await videos.deleteVideo(videoId);
}
