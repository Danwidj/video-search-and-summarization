// SPDX-License-Identifier: Apache-2.0

import { Readable } from 'node:stream';

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { MAX_R2_PUT_BYTES, putR2Video, r2ObjectExists, verifyR2Video } from '@/lib/r2/config';
import { firstFreeName, inspectUploadName, uploadKeyForName } from '@/lib/r2/names';

export const maxDuration = 120;

/**
 * Uploads the video directly to R2 and returns its durable object key,
 * `uploads/<file name>`. The original name is kept (see inspectUploadName); when
 * the name is taken the file is stored as `name-2.ext`, `name-3.ext`, ... and
 * an existing object is never overwritten.
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
    const filename = form.get('filename');
    if (!(file instanceof Blob) || typeof filename !== 'string' || !filename.trim()) {
      return NextResponse.json({ error: 'file and filename are required' }, { status: 400 });
    }

    if (file.size > MAX_R2_PUT_BYTES) {
      return NextResponse.json({ error: 'Video exceeds the R2 single-upload size limit' }, { status: 413 });
    }

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');

    const checked = inspectUploadName(filename);
    const name = await firstFreeName(checked.name, (candidate) => r2ObjectExists(config, uploadKeyForName(candidate)));
    const key = uploadKeyForName(name);
    const body = Readable.fromWeb(file.stream() as Parameters<typeof Readable.fromWeb>[0]);
    await putR2Video(config, key, body, file.type || 'video/mp4', file.size);
    await verifyR2Video(config, key, file.size);

    return NextResponse.json({ filePath: key, name });
  } catch (error) {
    if ((error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode === 412) {
      return NextResponse.json({ error: 'A file with this name was stored meanwhile; upload it again' }, { status: 409 });
    }
    return errorResponse(error, 'Could not upload the video to R2');
  }
}
