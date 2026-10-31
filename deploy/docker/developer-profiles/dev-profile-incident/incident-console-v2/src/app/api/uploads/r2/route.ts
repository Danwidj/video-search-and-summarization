// SPDX-License-Identifier: Apache-2.0

import { createReadStream } from 'node:fs';

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { putR2Video, r2ObjectExists, verifyR2Video } from '@/lib/r2/config';
import { firstFreeName, inspectUploadName, uploadKeyForName } from '@/lib/r2/names';
import { TranscodeError, prepareUpload } from '@/lib/video/transcode';

// Upload, probe, convert and store a 10-minute 4K phone clip: the conversion
// alone is allowed 25 minutes (lib/video/transcode.ts). Documented with the
// size cap in the profile .env (incident-console-v2 section).
export const maxDuration = 1800;

/**
 * The largest file the route accepts: a 10-minute 4K60 HEVC phone recording is
 * about 4 GB. The stored (converted) file is smaller and must also fit R2's
 * 5 GB single PutObject, which putR2Video checks.
 */
const MAX_UPLOAD_BYTES = 5 * 1024 ** 3;

/**
 * Converts the video to an H.264 MP4 when it is not one already, uploads it to
 * R2 and returns its durable object key, `uploads/<file name>.mp4`. The
 * original name is kept (see inspectUploadName) with an `.mp4` extension; when
 * the name is taken the file is stored as `name-2.mp4`, `name-3.mp4`, ... and
 * an existing object is never overwritten.
 *
 * This is the only upload: the browser hands the file to the console, which
 * keeps the R2 credentials server-side. `converted` in the answer says whether
 * ffmpeg ran or the file was stored byte for byte.
 */
export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const file = form.get('file');
    const filename = form.get('filename');
    if (!(file instanceof Blob) || typeof filename !== 'string' || !filename.trim()) {
      return NextResponse.json({ error: 'file and filename are required' }, { status: 400 });
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      return NextResponse.json({ error: 'Video exceeds the 5 GB upload limit' }, { status: 413 });
    }

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');

    const prepared = await prepareUpload(file);
    try {
      const checked = inspectUploadName(filename);
      const name = await firstFreeName(checked.name, (candidate) => r2ObjectExists(config, uploadKeyForName(candidate)));
      const key = uploadKeyForName(name);
      await putR2Video(config, key, createReadStream(prepared.path), 'video/mp4', prepared.size);
      await verifyR2Video(config, key, prepared.size);
      return NextResponse.json({ filePath: key, name, converted: prepared.converted });
    } finally {
      await prepared.cleanup();
    }
  } catch (error) {
    if (error instanceof TranscodeError) return NextResponse.json({ error: error.message }, { status: error.status });
    if ((error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode === 412) {
      return NextResponse.json({ error: 'A file with this name was stored meanwhile; upload it again' }, { status: 409 });
    }
    return errorResponse(error, 'Could not upload the video to R2');
  }
}
