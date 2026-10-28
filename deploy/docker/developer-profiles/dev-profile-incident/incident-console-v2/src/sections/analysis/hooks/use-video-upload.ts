// SPDX-License-Identifier: Apache-2.0

import { useCallback } from 'react';

import { inspectUploadName } from '@/lib/r2/names';
import { isValidR2Key } from '@/lib/r2/key';
import { thumbnailCaptureTime } from '@/lib/ui/thumbnail';
import { chunkedUpload } from '@/modules/videos/infrastructure/vst/chunked-upload';

export interface UploadedVideo {
  sensorId: string;
  filePath: string;
  filename: string;
}

interface UploadInitialization {
  url?: string;
}

interface ApiError {
  error?: string;
}

export interface UploadNameReport {
  /** The name the file will be stored under. */
  name: string;
  unsafeChars: string[];
  truncated: boolean;
  /** True when the file's own name is taken, so `name` carries a counter. */
  exists: boolean;
  existingName: string;
}

/** Asks the console what name an upload would get, before anything is sent. */
export async function checkUploadName(filename: string): Promise<UploadNameReport> {
  const response = await fetch('/api/uploads/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  const payload = (await response.json()) as UploadNameReport & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

async function initUpload(filename: string): Promise<UploadInitialization> {
  const response = await fetch('/api/uploads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  const payload = (await response.json()) as UploadInitialization & ApiError;
  if (!response.ok) throw new Error(payload.error || `Request failed with HTTP ${response.status}`);
  return payload;
}

/**
 * Uploads the video directly to R2 via the console's own server-side route.
 * Needed only when the chunk-upload response has no durable R2 object key —
 * the real VST/NvStreamer case, since only mock-backend's own reimplementation
 * fakes that field by doing its own R2 upload.
 */
async function uploadToR2(file: File, filename: string, signal: AbortSignal): Promise<string> {
  const form = new FormData();
  form.append('file', file, filename);
  form.append('filename', filename);
  const response = await fetch('/api/uploads/r2', { method: 'POST', body: form, signal });
  const payload = (await response.json()) as { filePath?: string } & ApiError;
  if (!response.ok || !isValidR2Key(payload.filePath)) {
    throw new Error(payload.error || 'Could not upload the video to R2');
  }
  return payload.filePath;
}

async function captureThumbnail(file: File): Promise<Blob> {
  const url = URL.createObjectURL(file);
  const video = document.createElement('video');
  video.muted = true;
  video.preload = 'metadata';
  video.playsInline = true;
  video.src = url;
  try {
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('Timed out reading video metadata')), 10_000);
      video.onloadedmetadata = () => {
        window.clearTimeout(timeout);
        resolve();
      };
      video.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error('Browser could not decode a thumbnail frame'));
      };
    });
    const target = thumbnailCaptureTime(video.duration);
    if (target > 0) {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Timed out seeking thumbnail frame')), 10_000);
        video.onseeked = () => {
          window.clearTimeout(timeout);
          resolve();
        };
        video.onerror = () => {
          window.clearTimeout(timeout);
          reject(new Error('Browser could not seek the thumbnail frame'));
        };
        video.currentTime = target;
      });
    } else {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Timed out decoding thumbnail frame')), 10_000);
        video.onloadeddata = () => {
          window.clearTimeout(timeout);
          resolve();
        };
        video.onerror = () => {
          window.clearTimeout(timeout);
          reject(new Error('Browser could not decode the thumbnail frame'));
        };
      });
    }

    const scale = Math.min(1, 640 / Math.max(video.videoWidth, 1), 360 / Math.max(video.videoHeight, 1));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Browser could not create a thumbnail canvas');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('Browser could not encode the thumbnail'))), 'image/webp', 0.78),
    );
  } finally {
    video.removeAttribute('src');
    video.load();
    URL.revokeObjectURL(url);
  }
}

async function uploadThumbnail(thumbnail: Blob, videoKey: string, signal: AbortSignal): Promise<void> {
  const form = new FormData();
  form.append('file', thumbnail, 'thumbnail.webp');
  form.append('videoKey', videoKey);
  const response = await fetch('/api/uploads/thumbnail', { method: 'POST', body: form, signal });
  if (!response.ok) {
    const payload = (await response.json()) as ApiError;
    throw new Error(payload.error || 'Could not upload the video thumbnail');
  }
}

/** Uploads a selected video and its thumbnail, returning the sensor ID and the R2 key the analysis reads. */
export function useVideoUpload() {
  const upload = useCallback(async (file: File, signal: AbortSignal, onProgress: (progress: number) => void): Promise<UploadedVideo> => {
    const thumbnail = captureThumbnail(file).catch(() => null);
    const filename = inspectUploadName(file.name).name;
    const initialized = await initUpload(filename);
    if (!initialized.url) throw new Error('The upload service did not return an upload URL');

    const uploaded = await chunkedUpload({
      file,
      fileName: filename,
      uploadUrl: initialized.url,
      // The development mock records only the current request body and does
      // not reassemble multiple chunks. A single request keeps the R2 object
      // as a valid video and matches v1's verified upload behavior. Restore
      // the helper's default chunk size when the real nvstreamer backend is
      // the active upload target and large-video limits are exercised.
      chunkSize: Math.max(file.size, 1),
      onProgress,
      abortSignal: signal,
    });
    if (!uploaded.sensorId) {
      throw new Error('Upload completed without a sensor ID');
    }

    // Mock-backend's chunk-upload response already carries a valid R2 key
    // (it does its own R2 upload); real VST/NvStreamer never returns one,
    // so fall back to uploading the file to R2 ourselves in that case.
    const filePath = isValidR2Key(uploaded.filePath) ? uploaded.filePath : await uploadToR2(file, filename, signal);

    const thumbnailBlob = await thumbnail;
    if (thumbnailBlob) await uploadThumbnail(thumbnailBlob, filePath, signal).catch(() => undefined);

    return { sensorId: uploaded.sensorId, filePath, filename: filePath.split('/').pop() || filename };
  }, []);

  return { upload };
}
