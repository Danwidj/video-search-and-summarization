// SPDX-License-Identifier: Apache-2.0

// Readable R2 object names for uploaded videos. Pure functions with no AWS SDK
// dependency, so the browser and the routes share one definition of "safe".

/** The longest stored file name (extension included), in characters. */
export const MAX_UPLOAD_NAME_LENGTH = 150;

/** Folder of every uploaded video: the object key is `uploads/<name>`. */
export const UPLOAD_PREFIX = 'uploads/';

/** Every stored video is an H.264 MP4 (lib/video/transcode.ts), so every stored name ends in this. */
export const STORED_EXTENSION = '.mp4';

const MAX_COUNTER = 999;

export interface UploadNameCheck {
  /** The name the file is stored under before any collision counter. */
  name: string;
  /** Distinct characters that were replaced with `_`, for the warning. */
  unsafeChars: string[];
  /** True when the name was shortened to fit MAX_UPLOAD_NAME_LENGTH. */
  truncated: boolean;
}

function splitExtension(name: string): { stem: string; ext: string } {
  const match = /^(.+?)(\.[A-Za-z0-9]{1,10})$/.exec(name);
  return match ? { stem: match[1], ext: match[2] } : { stem: name, ext: '' };
}

function fit(stem: string, ext: string, suffix = ''): string {
  const room = Math.max(1, MAX_UPLOAD_NAME_LENGTH - ext.length - suffix.length);
  return `${stem.slice(0, room)}${suffix}${ext}`;
}

function describe(char: string): string {
  return /\s/.test(char) ? 'space' : char;
}

/**
 * The stored name for an uploaded file. The original name is kept; a character
 * outside letters, digits and `. _ - ( ) + ,` is replaced with `_` and reported,
 * the extension becomes `.mp4` (the upload route converts anything else to an
 * H.264 MP4, so `clip.MOV` is stored as `clip.mp4`), and the name is shortened
 * only when it exceeds MAX_UPLOAD_NAME_LENGTH.
 */
export function inspectUploadName(original: string): UploadNameCheck {
  const unsafe = new Set<string>();
  const base = original.split(/[\\/]/).pop() ?? '';
  if (base.length !== original.length) unsafe.add('/');
  let name = base.trim().replace(/[^\p{L}\p{N}._()+,-]/gu, (char) => {
    unsafe.add(describe(char));
    return '_';
  });
  if (/\.{2,}/.test(name)) {
    unsafe.add('..');
    name = name.replace(/\.{2,}/g, '.');
  }
  if (name.startsWith('.')) {
    unsafe.add('.');
    name = `_${name.slice(1)}`;
  }
  if (name === '') name = 'video';
  const { stem } = splitExtension(name);
  const stored = `${stem}${STORED_EXTENSION}`;
  const truncated = stored.length > MAX_UPLOAD_NAME_LENGTH;
  return { name: truncated ? fit(stem, STORED_EXTENSION) : stored, unsafeChars: [...unsafe], truncated };
}

/** `name` with a counter before its extension: `clip.mp4`, then `clip-2.mp4`, `clip-3.mp4`. */
export function nameWithCounter(name: string, counter: number): string {
  if (counter <= 1) return name;
  const { stem, ext } = splitExtension(name);
  return fit(stem, ext, `-${counter}`);
}

/**
 * The first of `name`, `name-2`, `name-3`, ... for which `exists` is false.
 * Deterministic, so an upload never overwrites a stored file.
 */
export async function firstFreeName(name: string, exists: (candidate: string) => Promise<boolean>): Promise<string> {
  for (let counter = 1; counter <= MAX_COUNTER; counter += 1) {
    const candidate = nameWithCounter(name, counter);
    if (!(await exists(candidate))) return candidate;
  }
  throw new Error(`Too many files named like ${name}`);
}

export function uploadKeyForName(name: string): string {
  return `${UPLOAD_PREFIX}${name}`;
}
