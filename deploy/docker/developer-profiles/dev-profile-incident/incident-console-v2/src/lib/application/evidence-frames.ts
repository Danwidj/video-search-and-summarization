// SPDX-License-Identifier: Apache-2.0

// Frame and crop use cases for replacing or adding evidence: the frame of a
// video at a second, and a crop of that frame stored as a new R2 image. They
// depend on the video port and on functions for reading the video and writing
// the image, so they never import ffmpeg or R2 and are tested with fakes.

import type { FrameRegion } from '@/lib/evidence/frame-geometry';
import { assertWithinVideo, FrameRequestError, parseItemId, parseRegion, parseSeconds } from '@/lib/evidence/frame-request';
import type { VideoRepository } from '@/lib/ports/videos';
import { isValidR2Key } from '@/lib/r2/key';
import { uploadedEvidenceKey } from '@/modules/reports/domain/revision';

/** Reads a video's length in seconds (null when it cannot be read) and one JPEG frame, optionally cropped. */
export interface FrameSource {
  durationSeconds(storageKey: string): Promise<number | null>;
  frame(storageKey: string, seconds: number, region: FrameRegion | null): Promise<Buffer>;
}

/** Writes a new image object. Must never replace an existing key; callers pass a fresh one. */
export type StoreEvidenceImage = (key: string, jpeg: Buffer) => Promise<void>;

export interface EvidenceFrameDeps {
  videos: Pick<VideoRepository, 'getVideo'>;
  source: FrameSource;
}

export interface EvidenceCropDeps extends EvidenceFrameDeps {
  store: StoreEvidenceImage;
  newUuid: () => string;
}

async function checkedVideo({ videos, source }: EvidenceFrameDeps, videoId: string, rawSeconds: unknown) {
  const seconds = parseSeconds(rawSeconds);
  const video = await videos.getVideo(videoId);
  if (!video) throw new FrameRequestError(404, 'Video not found');
  if (!isValidR2Key(video.storageKey)) throw new FrameRequestError(409, 'This video has no stored R2 object to read frames from');
  assertWithinVideo(seconds, await source.durationSeconds(video.storageKey));
  return { seconds, storageKey: video.storageKey };
}

/** The full frame (JPEG) of the video at `rawSeconds`. */
export async function getVideoFrame(deps: EvidenceFrameDeps, videoId: string, rawSeconds: unknown): Promise<Buffer> {
  const { seconds, storageKey } = await checkedVideo(deps, videoId, rawSeconds);
  return deps.source.frame(storageKey, seconds, null);
}

export interface EvidenceCropRequest {
  itemId: unknown;
  timestampSeconds: unknown;
  /** {x, y, w, h} as fractions (0-1) of the frame. */
  region: unknown;
}

export interface EvidenceCrop {
  /** The new R2 key, evidence/<videoId>/<uuid>/<itemId>.jpg, ready for an evidence entry's `image`. */
  image: string;
  jpeg: Buffer;
  timestampSeconds: number;
  region: FrameRegion;
}

/**
 * Crops the frame at the timestamp to the rectangle and stores it under a new
 * unique key. Nothing is overwritten or deleted: earlier revisions keep the
 * keys they reference.
 */
export async function createEvidenceCrop(deps: EvidenceCropDeps, videoId: string, request: EvidenceCropRequest): Promise<EvidenceCrop> {
  const itemId = parseItemId(request.itemId);
  const region = parseRegion(request.region);
  const { seconds, storageKey } = await checkedVideo(deps, videoId, request.timestampSeconds);
  const jpeg = await deps.source.frame(storageKey, seconds, region);
  const image = uploadedEvidenceKey(videoId, deps.newUuid(), itemId);
  await deps.store(image, jpeg);
  return { image, jpeg, timestampSeconds: seconds, region };
}
