// SPDX-License-Identifier: Apache-2.0

// VideoObjectStore over Cloudflare R2, using the console's R2 configuration.

import type { ServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl, readR2VideoDurationSeconds, verifyR2Video } from '@/lib/r2/config';
import type { VideoObjectStore } from '@/modules/analysis/domain/VideoObjectStore';

export class R2VideoObjectStore implements VideoObjectStore {
  private readonly config: ServiceConfiguration;

  constructor(config: ServiceConfiguration) {
    this.config = config;
  }

  verify(key: string): Promise<{ contentLength: number }> {
    return verifyR2Video(this.config, key);
  }

  playbackUrl(key: string): Promise<string> {
    return createR2PlaybackUrl(this.config, key);
  }

  durationSeconds(key: string, contentLength: number): Promise<number | null> {
    return readR2VideoDurationSeconds(this.config, key, contentLength);
  }
}
