// SPDX-License-Identifier: Apache-2.0

import { Readable } from 'node:stream';

import type { EvidenceCropDeps, FrameSource, StoreEvidenceImage } from '@/lib/application/evidence-frames';
import { getServiceConfiguration, isR2Configured, type ServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl, putR2Video, readR2VideoDurationSeconds, verifyR2Video } from '@/lib/r2/config';
import { extractFrameJpeg } from '@/lib/video/ffmpeg-frame';

/** Frames of a video in R2: its length from the MP4 header, a frame decoded by ffmpeg over a signed URL. */
export function r2FrameSource(config: ServiceConfiguration): FrameSource {
  return {
    async durationSeconds(storageKey) {
      const { contentLength } = await verifyR2Video(config, storageKey);
      return readR2VideoDurationSeconds(config, storageKey, contentLength);
    },
    async frame(storageKey, seconds, region) {
      return extractFrameJpeg(await createR2PlaybackUrl(config, storageKey), seconds, region);
    },
  };
}

/** Puts a JPEG at a key and reads its size back, like the evidence-image upload. */
export function r2EvidenceImageStore(config: ServiceConfiguration): StoreEvidenceImage {
  return async (key, jpeg) => {
    await putR2Video(config, key, Readable.from([jpeg]), 'image/jpeg', jpeg.length);
    await verifyR2Video(config, key, jpeg.length);
  };
}

export function r2FrameConfiguration(): ServiceConfiguration {
  const config = getServiceConfiguration();
  if (!isR2Configured(config)) throw new Error('R2 is not configured');
  return config;
}
