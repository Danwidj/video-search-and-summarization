// SPDX-License-Identifier: Apache-2.0

// Video length from an MP4 file's moov/mvhd header, read by byte ranges.
//
// Validation policy core-scored-v1 checks the incident window against the real
// video length, which is runtime context rather than anything in the schema.
// This reads it without ffmpeg: walk the top-level boxes (ftyp, mdat, moov ...
// in any order - moov is often at the end) by reading only their headers, then
// read moov and take mvhd duration / timescale. Anything malformed or
// unreadable gives null (length unknown, so the rule is not applied); it never
// guesses. Mirrors eval/video_duration.py.

/** readRange(offset, length) -> up to `length` bytes starting at `offset`. */
export type ReadRange = (offset: number, length: number) => Promise<Uint8Array>;

// moov holds the sample tables; a few MB is typical, far more is not a header.
export const MAX_MOOV_BYTES = 64 * 1024 * 1024;
const MAX_TOP_LEVEL_BOXES = 1024;

function view(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

function boxType(bytes: Uint8Array, offset: number): string {
  return String.fromCharCode(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
}

function uint64(data: DataView, offset: number): number {
  return data.getUint32(offset) * 2 ** 32 + data.getUint32(offset + 4);
}

/** Duration from the mvhd box among moov's children. */
function mvhdSeconds(moov: Uint8Array): number | null {
  const data = view(moov);
  let offset = 0;
  while (offset + 8 <= moov.length) {
    let size = data.getUint32(offset);
    let header = 8;
    if (size === 1) {
      if (offset + 16 > moov.length) return null;
      size = uint64(data, offset + 8);
      header = 16;
    } else if (size === 0) {
      size = moov.length - offset;
    }
    if (size < header || offset + size > moov.length) return null;
    if (boxType(moov, offset + 4) === 'mvhd') {
      const body = offset + header;
      const end = offset + size;
      if (body >= end) return null;
      const version = moov[body];
      let timescale: number;
      let duration: number;
      if (version === 1 && end - body >= 4 + 16 + 12) {
        timescale = data.getUint32(body + 4 + 16);
        duration = uint64(data, body + 4 + 16 + 4);
      } else if (version === 0 && end - body >= 4 + 8 + 8) {
        timescale = data.getUint32(body + 4 + 8);
        duration = data.getUint32(body + 4 + 8 + 4);
      } else {
        return null;
      }
      if (timescale === 0 || duration === 0 || duration === 0xffffffff || duration >= 2 ** 64 - 1) return null;
      return duration / timescale;
    }
    offset += size;
  }
  return null;
}

/** Video length in seconds from an MP4's mvhd, or null when it cannot be read. */
export async function mp4DurationSeconds(readRange: ReadRange, fileSize: number): Promise<number | null> {
  try {
    let offset = 0;
    for (let index = 0; index < MAX_TOP_LEVEL_BOXES; index += 1) {
      if (offset + 8 > fileSize) return null;
      const head = await readRange(offset, 16);
      if (head.length < 8) return null;
      const data = view(head);
      let size = data.getUint32(0);
      let header = 8;
      if (size === 1) {
        if (head.length < 16) return null;
        size = uint64(data, 8);
        header = 16;
      } else if (size === 0) {
        size = fileSize - offset;
      }
      if (size < header || offset + size > fileSize) return null;
      if (boxType(head, 4) === 'moov') {
        if (size > MAX_MOOV_BYTES) return null;
        const moov = await readRange(offset + header, size - header);
        if (moov.length !== size - header) return null;
        return mvhdSeconds(moov);
      }
      offset += size;
    }
    return null;
  } catch {
    return null;
  }
}
