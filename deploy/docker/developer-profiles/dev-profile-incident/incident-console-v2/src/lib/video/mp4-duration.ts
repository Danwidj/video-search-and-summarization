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

/** The mvhd box body among moov's children: the version, then the fields after it. */
function mvhdBody(moov: Uint8Array): { data: DataView; body: number; end: number } | null {
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
      return body >= end ? null : { data, body, end };
    }
    offset += size;
  }
  return null;
}

/** Duration from the mvhd box among moov's children. */
function mvhdSeconds(moov: Uint8Array): number | null {
  const box = mvhdBody(moov);
  if (!box) return null;
  const { data, body, end } = box;
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

// MP4 counts seconds from 1904-01-01 UTC; the Unix epoch is this many seconds later.
const MP4_EPOCH_OFFSET_SECONDS = 2_082_844_800;

/** The mvhd creation time as an ISO instant; null when unset (0) or not a plausible past instant. */
function mvhdCreatedAt(moov: Uint8Array, now: Date): string | null {
  const box = mvhdBody(moov);
  if (!box) return null;
  const { data, body, end } = box;
  const version = moov[body];
  let seconds: number;
  if (version === 1 && end - body >= 4 + 8) seconds = uint64(data, body + 4);
  else if (version === 0 && end - body >= 4 + 4) seconds = data.getUint32(body + 4);
  else return null;
  if (seconds === 0) return null;
  const unixMs = (seconds - MP4_EPOCH_OFFSET_SECONDS) * 1000;
  if (!Number.isFinite(unixMs) || unixMs <= 0 || unixMs > now.getTime()) return null;
  return new Date(unixMs).toISOString();
}

/** Reads moov and hands it to `read`; null when the file has no readable moov. */
async function withMoov<T>(readRange: ReadRange, fileSize: number, read: (moov: Uint8Array) => T | null): Promise<T | null> {
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
        return read(moov);
      }
      offset += size;
    }
    return null;
  } catch {
    return null;
  }
}

/** Video length in seconds from an MP4's mvhd, or null when it cannot be read. */
export function mp4DurationSeconds(readRange: ReadRange, fileSize: number): Promise<number | null> {
  return withMoov(readRange, fileSize, mvhdSeconds);
}

/** When the file says it was recorded (mvhd creation time, ISO 8601 UTC), or null when it carries none. */
export function mp4RecordedAt(readRange: ReadRange, fileSize: number, now: Date = new Date()): Promise<string | null> {
  return withMoov(readRange, fileSize, (moov) => mvhdCreatedAt(moov, now));
}
