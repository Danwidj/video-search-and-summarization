// SPDX-License-Identifier: Apache-2.0

// The pixel size of a JPEG, read from its header. Pure, browser-safe, no decoding.

/** The size from the start-of-frame marker; null when the bytes are not a JPEG with one. */
export function jpegSize(jpeg: ArrayLike<number>): { width: number; height: number } | null {
  if (jpeg.length < 4 || jpeg[0] !== 0xff || jpeg[1] !== 0xd8) return null;
  let at = 2;
  while (at + 9 < jpeg.length) {
    if (jpeg[at] !== 0xff) return null;
    const marker = jpeg[at + 1];
    if (marker === 0xff) {
      at += 1;
      continue;
    }
    // SOF0-SOF15 carry the size, apart from DHT (c4), JPG (c8) and DAC (cc).
    if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc)
      return { height: (jpeg[at + 5] << 8) | jpeg[at + 6], width: (jpeg[at + 7] << 8) | jpeg[at + 8] };
    at += 2 + ((jpeg[at + 2] << 8) | jpeg[at + 3]);
  }
  return null;
}
