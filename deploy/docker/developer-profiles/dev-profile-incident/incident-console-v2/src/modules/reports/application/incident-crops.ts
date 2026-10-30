// SPDX-License-Identifier: Apache-2.0

// The searchable crops of an incident revision: one embedding call per camera, because item ids repeat from
// camera to camera, and each crop is tagged with its source video. Shared by Save, Mark official and the
// searchable-crops step.

import type { ReportEnvelope } from '@/modules/reports/domain/envelope';
import { isCameraEvidence } from '@/modules/reports/domain/camera-evidence';
import type { IncidentCrop, IncidentVideo } from '@/modules/reports/domain/IncidentReportRepository';
import { officialCrops, type EvidenceEntry } from '@/modules/reports/domain/revision';
import type { EmbedEvidence } from '@/modules/reports/application/types';

/**
 * The crops a revision is searchable with. Only cameras the revision covers and whose video is still in the
 * incident take part (the database refuses a crop of any other video); a camera with no evidence image adds
 * none and costs no embedding call.
 */
export async function incidentCrops(
  envelope: ReportEnvelope,
  evidence: EvidenceEntry[],
  covered: readonly string[],
  videos: readonly IncidentVideo[],
  embed: EmbedEvidence,
): Promise<IncidentCrop[]> {
  const crops: IncidentCrop[] = [];
  for (const camera of envelope.cameras) {
    const video = videos.find((candidate) => candidate.videoId === camera.video);
    if (!video || !covered.includes(camera.video)) continue;
    const mine = evidence.filter((entry) => entry.image && isCameraEvidence(entry, camera.video, video.storageKey));
    if (!mine.length) continue;
    const embeddings = await embed(mine);
    for (const crop of officialCrops(camera.report, mine, embeddings)) crops.push({ ...crop, video_id: camera.video });
  }
  return crops;
}
