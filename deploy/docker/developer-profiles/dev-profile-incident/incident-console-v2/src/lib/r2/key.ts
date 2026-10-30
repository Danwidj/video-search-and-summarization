// SPDX-License-Identifier: Apache-2.0

/**
 * True when `key` is shaped like a durable R2 object key rather than a local
 * filesystem path. Guards against VST/NvStreamer's own `filePath` values,
 * which are either absolute (its shipped config) or relative starting with
 * `./` (its in-code default streamer directory) — neither is ever a real R2
 * object key. No AWS SDK dependency so it is safe to import from client code.
 */
export function isValidR2Key(key: unknown): key is string {
  return typeof key === 'string' && key.length > 0 && !key.startsWith('/') && !key.startsWith('.') && !key.includes('..');
}

/**
 * Converts a logical R2 key (prefix-free, as stored in the DB) to the physical
 * key used for the S3 call by prepending `R2_KEY_PREFIX`. When the prefix is
 * absent the logical and physical keys are identical.
 */
export function r2PhysicalKey(prefix: string | undefined, logicalKey: string): string {
  return prefix ? `${prefix}${logicalKey}` : logicalKey;
}

/**
 * Strips the global prefix from a physical key returned by S3, yielding the
 * logical key stored in the DB. No-op when the prefix is absent or the key
 * does not start with it (defensive: returns the key unchanged).
 */
export function r2LogicalKey(prefix: string | undefined, physicalKey: string): string {
  if (prefix && physicalKey.startsWith(prefix)) return physicalKey.slice(prefix.length);
  return physicalKey;
}

export function thumbnailKeyForVideo(videoKey: string): string {
  if (!isValidR2Key(videoKey)) throw new Error('Invalid R2 video object key');
  return `thumbnails/${videoKey}.webp`;
}
