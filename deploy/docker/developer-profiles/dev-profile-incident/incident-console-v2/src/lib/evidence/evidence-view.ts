// SPDX-License-Identifier: Apache-2.0

// What the report shows for one evidence item: the whole video frame with the box drawn on it, never a cut-out crop.
// Pure functions, no I/O, browser-safe. A box that covers (nearly) the whole frame is how items analysed before the
// agent marked "not located" stored a fallback, so it is read as not located rather than drawn as a real box.

import { boxRegion } from '@/lib/evidence/frame-geometry';
import type { ItemEvidence } from '@/modules/reports/domain/report-view';

export interface EvidenceDisplay {
  /** The whole frame to show; null when there is none to read (the stored crop stands in, whole). */
  frameSrc: string | null;
  /** The stored crop, shown whole when the frame cannot be had. */
  src: string | null;
  /** The box to draw on the frame; null when the object was not located. */
  box: readonly number[] | null;
  notLocated: boolean;
}

const WHOLE_FRAME = 0.98;

/** True for a box that covers the whole frame in both directions: the old fallback, not an object. */
export function coversWholeFrame(box: readonly number[] | null | undefined): boolean {
  const region = boxRegion(box);
  return !!region && region.w >= WHOLE_FRAME && region.h >= WHOLE_FRAME;
}

/** The frame the console cuts from the stored video at a second (the route reads the video from R2). */
export function videoFrameUrl(incidentId: string, video: string, seconds: number): string {
  return `/api/reports/${encodeURIComponent(incidentId)}/frame?video=${encodeURIComponent(video)}&t=${Math.max(0, Math.round(seconds))}`;
}

/**
 * The frame, box and note for one item. The stored frame comes first. An item analysed before frames were stored, or one a
 * reviewer replaced with a picked frame, has a box and a second, so its frame is cut from the stored video. Without any of
 * those the stored crop is shown whole.
 */
export function evidenceDisplay(evidence: ItemEvidence | null | undefined, incidentId: string, video: string): EvidenceDisplay {
  if (!evidence) return { frameSrc: null, src: null, box: null, notLocated: false };
  const notLocated = evidence.located === false || coversWholeFrame(evidence.boundingBox);
  const box = notLocated || !boxRegion(evidence.boundingBox) ? null : evidence.boundingBox;
  const seconds = evidence.boxSeconds ?? evidence.timestampSeconds;
  const fromVideo = seconds !== null && (box !== null || notLocated) ? videoFrameUrl(incidentId, video, seconds) : null;
  return { frameSrc: evidence.frameUrl ?? fromVideo, src: evidence.imageUrl, box, notLocated };
}

/** "IMG_8206 · E1": the video (without its extension) and the camera's own item id, which repeats from video to video. */
export function evidenceLabel(video: string, id: string): string {
  return `${video.replace(/\.[A-Za-z0-9]{1,5}$/, '')} · ${id}`;
}
