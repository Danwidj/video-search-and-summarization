// SPDX-License-Identifier: Apache-2.0

// VideoObjectStore: the R2 object an analysis reads. Keys are R2 keys
// (videos.filepath); the adapter owns the bucket configuration.

export interface VideoObjectStore {
  /** Confirms the object exists and returns its byte length. */
  verify(key: string): Promise<{ contentLength: number }>;
  /** A short-lived signed URL the model or agent fetches the video from. */
  playbackUrl(key: string): Promise<string>;
  /** The video's length from its MP4 header; null when it cannot be read. */
  durationSeconds(key: string, contentLength: number): Promise<number | null>;
  /** When the file says it was recorded (ISO 8601 UTC); null when it carries no usable time. */
  recordedAt(key: string, contentLength: number): Promise<string | null>;
}
