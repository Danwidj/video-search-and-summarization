// SPDX-License-Identifier: Apache-2.0

// Delete an incident: every video it holds, with its stored objects, and then the incident itself.

import type { IncidentId } from '@/modules/reports/domain/IncidentReportRepository';
import { deleteVideoObjectsAndRow, type RemoveVideoPorts } from '@/modules/reports/application/remove-video';

export interface DeleteIncidentResult {
  incidentId: IncidentId;
  /** The names of the videos deleted, in the order they went. */
  deletedVideoIds: string[];
}

/**
 * Deletes each video of the incident like a remove-entirely (objects first, then the row); the last
 * video's removal deletes the incident row, and with it the revisions and crops. A failure throws
 * with the videos not yet reached still in place, so the delete can be repeated. An incident with no
 * videos has nothing in storage, so only its row goes. Throws StoreRejection 'not-found' for an
 * incident that does not exist.
 */
export async function deleteIncident(ports: RemoveVideoPorts, incidentId: IncidentId): Promise<DeleteIncidentResult> {
  const videos = await ports.videos.listVideos(incidentId);
  if (videos.length === 0) {
    await ports.videos.deleteEmptyIncident(incidentId);
    return { incidentId, deletedVideoIds: [] };
  }
  const deletedVideoIds: string[] = [];
  for (const { videoId } of videos) {
    await deleteVideoObjectsAndRow(ports, videoId);
    deletedVideoIds.push(videoId);
  }
  return { incidentId, deletedVideoIds };
}
