// SPDX-License-Identifier: Apache-2.0

import { useCallback } from 'react';

import { inspectUploadName } from '@/lib/r2/names';
import { isValidR2Key } from '@/lib/r2/key';
import { thumbnailCaptureTime } from '@/lib/ui/thumbnail';

export interface UploadedVideo {
  filePath: string;
  filename: string;
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

/**
 * Uploads the video directly to R2 via the console's own server-side route,
 * which keeps the R2 credentials server-side, and returns its R2 key.
 * XMLHttpRequest rather than fetch, because only it reports upload progress.
 */
function uploadToR2(file: File, filename: string, signal: AbortSignal, onProgress: (progress: number) => void): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error('Upload was cancelled'));
      return;
    }
    const form = new FormData();
    form.append('file', file, filename);
    form.append('filename', filename);
    const request = new XMLHttpRequest();
    const cancel = () => request.abort();
    signal.addEventListener('abort', cancel, { once: true });
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      signal.removeEventListener('abort', cancel);
      let payload: { filePath?: string } & ApiError = {};
      try {
        payload = JSON.parse(request.responseText) as typeof payload;
      } catch {
        // A non-JSON answer falls through to the generic error below.
      }
      if (request.status >= 200 && request.status < 300 && isValidR2Key(payload.filePath)) {
        onProgress(100);
        resolve(payload.filePath);
      } else {
        reject(new Error(payload.error || `Could not upload the video to R2 (HTTP ${request.status})`));
      }
    };
    request.onerror = () => {
      signal.removeEventListener('abort', cancel);
      reject(new Error('Could not upload the video to R2'));
    };
    request.onabort = () => {
      signal.removeEventListener('abort', cancel);
      reject(new Error('Upload was cancelled'));
    };
    request.open('POST', '/api/uploads/r2');
    request.send(form);
  });
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

/** Uploads a selected video once, to R2, and its thumbnail, returning the R2 key the analysis reads. */
export async function uploadVideo(file: File, signal: AbortSignal, onProgress: (progress: number) => void): Promise<UploadedVideo> {
  const thumbnail = captureThumbnail(file).catch(() => null);
  const filename = inspectUploadName(file.name).name;
  const filePath = await uploadToR2(file, filename, signal, onProgress);

  const thumbnailBlob = await thumbnail;
  if (thumbnailBlob) await uploadThumbnail(thumbnailBlob, filePath, signal).catch(() => undefined);

  return { filePath, filename: filePath.split('/').pop() || filename };
}

export function useVideoUpload() {
  const upload = useCallback(uploadVideo, []);
  return { upload };
}
