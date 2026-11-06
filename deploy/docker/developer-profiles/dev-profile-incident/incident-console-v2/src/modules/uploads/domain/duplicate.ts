// SPDX-License-Identifier: Apache-2.0

// A repeat upload: the same file content as a video already in the library, or
// as a job still queued or running. Browser-safe (the upload page imports it).
// The content is identified by the SHA-256 of the file as the reviewer uploaded
// it, before any conversion (see .docs/decisions.md, 2026-11-06 repeat uploads).

export const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export const isSha256 = (value: unknown): value is string => typeof value === 'string' && SHA256_PATTERN.test(value);

/** Where the same content already is: a video in the library (with a report page), or a job that has not produced one yet. */
export interface DuplicateUpload {
  kind: 'video' | 'job';
  /** The stored file name of the existing video or job. */
  name: string;
  videoId: string | null;
  jobId: number | null;
}

export const duplicateMessage = (duplicate: DuplicateUpload): string =>
  duplicate.kind === 'video'
    ? `This video is already in the library as ${duplicate.name}. Nothing was uploaded.`
    : `This video is already queued for analysis as ${duplicate.name}. Nothing was uploaded.`;

/** Thrown when the content is already stored or queued; the routes answer it with HTTP 409 and the duplicate. */
export class DuplicateUploadError extends Error {
  readonly duplicate: DuplicateUpload;

  constructor(duplicate: DuplicateUpload) {
    super(duplicateMessage(duplicate));
    this.name = 'DuplicateUploadError';
    this.duplicate = duplicate;
  }
}

/** The existing report's page, or null while the duplicate is only a queued job. */
export const duplicateReportPath = (duplicate: DuplicateUpload): string | null =>
  duplicate.kind === 'video' && duplicate.videoId ? `/reports/${encodeURIComponent(duplicate.videoId)}` : null;

/** The 23505 a unique index raised, as PostgREST words it (HTTP 409 with SQLSTATE 23505 in the body). */
export const isUniqueViolation = (error: unknown): boolean => error instanceof Error && /HTTP 409|23505|duplicate key/.test(error.message);

/** A query or write naming content_sha256 before the migration has run: the code then behaves as it did before. */
export const isMissingHashColumn = (error: unknown): boolean =>
  error instanceof Error &&
  /content_sha256/.test(error.message) &&
  /42703|PGRST204|PGRST100|does not exist|Could not find/.test(error.message);
