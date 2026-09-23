// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { putR2Video } from '@/lib/r2/config';

export const maxDuration = 120;

/**
 * Uploads the video directly to R2 and returns its durable object key.
 *
 * Real VST/NvStreamer's chunk-upload response never includes a durable R2
 * object key — only mock-backend's own reimplementation does its own R2
 * upload to fake that field. This route lets the browser hand the file to
 * the console itself for that case, keeping R2 credentials server-side only.
 */
export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const file = form.get('file');
    const sensorId = form.get('sensorId');
    const filename = form.get('filename');
    if (!(file instanceof Blob) || typeof sensorId !== 'string' || !sensorId.trim() || typeof filename !== 'string' || !filename.trim()) {
      return NextResponse.json({ error: 'file, sensorId, and filename are required' }, { status: 400 });
    }

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');

    const safeName = filename.replace(/[^A-Za-z0-9._-]/g, '') || 'video.mp4';
    const key = `uploads/${encodeURIComponent(sensorId.trim())}/${safeName}`;
    const bytes = new Uint8Array(await file.arrayBuffer());
    await putR2Video(config, key, bytes, file.type || 'video/mp4');

    return NextResponse.json({ filePath: key });
  } catch (error) {
    return errorResponse(error, 'Could not upload the video to R2');
  }
}
