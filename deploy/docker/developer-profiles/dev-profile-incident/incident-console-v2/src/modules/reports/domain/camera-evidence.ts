// SPDX-License-Identifier: Apache-2.0

// Which evidence entries of a revision belong to which camera. A revision keeps one flat evidence list for the
// whole incident, and item ids (E1, I1, A1) repeat from camera to camera, so an entry is told apart by the
// video it names (an entry may carry `video`) or, failing that, by its image sitting in the video's evidence
// folder. Pure functions, no I/O.

import { isEvidenceKeyOfVideo, type EvidenceEntry } from '@/modules/reports/domain/revision';

/** Whether the entry belongs to the camera of `videoName`, whose R2 object key is `storageKey` (null when none is recorded). */
export function isCameraEvidence(entry: EvidenceEntry, videoName: string, storageKey: string | null): boolean {
  if (typeof entry.video === 'string') return entry.video === videoName;
  return storageKey !== null && typeof entry.image === 'string' && isEvidenceKeyOfVideo(entry.image, storageKey);
}

/** The evidence split into one camera's entries and everyone else's (entries no camera can be told for stay with the others). */
export function splitCameraEvidence(
  evidence: EvidenceEntry[],
  videoName: string,
  storageKey: string | null,
): { camera: EvidenceEntry[]; others: EvidenceEntry[] } {
  const camera: EvidenceEntry[] = [];
  const others: EvidenceEntry[] = [];
  for (const entry of evidence) (isCameraEvidence(entry, videoName, storageKey) ? camera : others).push(entry);
  return { camera, others };
}
