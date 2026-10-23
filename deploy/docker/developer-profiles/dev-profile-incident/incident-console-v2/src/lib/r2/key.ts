// SPDX-License-Identifier: Apache-2.0

/**
 * True when `key` is shaped like a durable R2 object key rather than a local
 * filesystem path. Guards against VST/NvStreamer's own `filePath` values,
 * which are either absolute (its shipped config) or relative starting with
 * `./` (its in-code default streamer directory) — neither is ever a real R2
 * object key. No AWS SDK dependency so it is safe to import from client code.
 */
export function isValidR2Key(key: unknown): key is string {
  return (
    typeof key === 'string' &&
    key.length > 0 &&
    !key.startsWith('/') &&
    !key.startsWith('.') &&
    !key.includes('..')
  );
}

export function thumbnailKeyForVideo(videoKey: string): string {
  if (!isValidR2Key(videoKey)) throw new Error('Invalid R2 video object key');
  return `thumbnails/${videoKey}.webp`;
}
