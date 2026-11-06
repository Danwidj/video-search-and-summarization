// SPDX-License-Identifier: Apache-2.0

import type { ServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl } from '@/lib/r2/config';

/** A track holds at most 5 samples a second of about 50 bytes each; anything this large is not one. */
const MAX_STORED_JSON_BYTES = 4 * 1024 * 1024;

export class StoredJsonError extends Error {}

/**
 * Reads one stored JSON object (an evidence track) through a signed URL, on the server because R2 has no CORS rule for the
 * console origin. Throws StoredJsonError when it cannot be read; null when it is not JSON. Errors never name the key.
 */
export function readStoredJson(config: ServiceConfiguration): (key: string) => Promise<unknown> {
  return async (key) => {
    const response = await fetch(await createR2PlaybackUrl(config, key), { cache: 'no-store' });
    if (!response.ok) throw new StoredJsonError(`The stored track returned HTTP ${response.status}`);
    const body = await response.text();
    if (body.length > MAX_STORED_JSON_BYTES) throw new StoredJsonError('The stored track is too large');
    try {
      return JSON.parse(body) as unknown;
    } catch {
      return null;
    }
  };
}
