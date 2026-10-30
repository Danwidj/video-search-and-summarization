// SPDX-License-Identifier: Apache-2.0

// Remove a video from its incident: delete it entirely, or move it to an incident of its own.

import type { IncidentVideoRepository, VideoMove, VideoRemoval } from '@/modules/videos/domain/IncidentVideoRepository';
import { evidenceFolder, isEvidenceKeyOfVideo } from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';
import type { EvidenceObjectStore, RemoveStoredVideo, RemoveVstSensor } from '@/modules/reports/application/types';

export type RemoveChoice = 'delete' | 'move';

export type RemoveVideoResult = ({ choice: 'delete' } & VideoRemoval) | ({ choice: 'move' } & VideoMove);

export interface RemoveVideoPorts {
  videos: Pick<IncidentVideoRepository, 'getVideo' | 'listVideos' | 'removeVideo' | 'moveVideoToNewIncident' | 'deleteEmptyIncident'>;
  evidence: EvidenceObjectStore;
  removeStoredVideo: RemoveStoredVideo;
  removeVstSensor: RemoveVstSensor;
}

/**
 * Deletes the video's stored objects first (the video, its thumbnail and every evidence image under
 * evidence/<video key>/), then its VST camera, then its row (analyses and crops go with it; the incident's revisions stay
 * as history, and the last video takes the incident with it).
 *
 * Objects go before rows because the orphan sweep refuses a video that has no row: once the row is
 * gone nothing could find its images again. The camera goes just before the row for the same reason:
 * the row holds the sensor id (videos.source). Any listing or removal failure throws before the row is
 * deleted, so the delete can be repeated (removing an absent object or camera succeeds).
 */
export async function deleteVideoObjectsAndRow(
  { videos, evidence, removeStoredVideo, removeVstSensor }: RemoveVideoPorts,
  videoId: string,
): Promise<VideoRemoval> {
  const video = await videos.getVideo(videoId);
  if (!video) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
  if (video.storageKey == null) throw new Error('Video has no R2 object key');
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
  await removeVstSensor({ videoId, sensorId: video.source });
  return videos.removeVideo(videoId);
}

/**
 * 'delete' removes the video entirely (see deleteVideoObjectsAndRow). 'move' makes it a new incident
 * of its own, analyses and crops following it, and touches no file; the caller then builds that
 * incident's first report. Moving an incident's last video is refused (StoreRejection 'invalid').
 */
export async function removeVideoFromIncident(ports: RemoveVideoPorts, videoId: string, choice: RemoveChoice): Promise<RemoveVideoResult> {
  if (choice === 'move') return { choice, ...(await ports.videos.moveVideoToNewIncident(videoId)) };
  return { choice, ...(await deleteVideoObjectsAndRow(ports, videoId)) };
}
