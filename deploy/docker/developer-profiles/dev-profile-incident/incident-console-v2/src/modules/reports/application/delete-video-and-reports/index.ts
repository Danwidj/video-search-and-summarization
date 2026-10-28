// SPDX-License-Identifier: Apache-2.0

// Delete video and reports: removes a whole video, its stored objects first.

import type { VideoRepository } from '@/modules/videos/domain/VideoRepository';
import { evidenceFolder, isEvidenceKeyOfVideo } from '@/modules/reports/domain/revision';
import type { EvidenceObjectStore, RemoveStoredVideo } from '@/modules/reports/application/types';

/**
 * Deletes the whole video: its stored objects first (the video, its thumbnail
 * and every evidence image under evidence/<video key>/), then the video row
 * (revisions, evidence crops and query results cascade) and the run records
 * that name only this video. Revisions are append-only, so there is no
 * deleting a single one.
 *
 * Objects go before rows because the orphan sweep refuses a video that has no
 * row: once the row is gone nothing could find its images again. Any listing
 * or removal failure throws before the row is deleted, so the delete can be
 * repeated (removing an absent object succeeds).
 */
export async function deleteVideoAndReports(
  videos: VideoRepository,
  evidence: EvidenceObjectStore,
  videoId: string,
  removeStoredVideo: RemoveStoredVideo,
): Promise<void> {
  const video = await videos.getVideo(videoId);
  if (video?.storageKey == null) throw new Error('Video has no R2 object key');
  const videoKey = video.storageKey;
  await removeStoredVideo(videoKey);
  const images = (await evidence.list(evidenceFolder(videoKey))).filter(({ key }) => isEvidenceKeyOfVideo(key, videoKey));
  const failures: string[] = [];
  for (const { key } of images) {
    try {
      await evidence.remove(key);
    } catch (error) {
      failures.push(`${key}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  if (failures.length > 0) {
    throw new Error(
      `Could not remove ${failures.length} of ${images.length} evidence images, so the video was kept: ${failures.join('; ')}`,
    );
  }
  await videos.deleteVideo(videoId);
}
