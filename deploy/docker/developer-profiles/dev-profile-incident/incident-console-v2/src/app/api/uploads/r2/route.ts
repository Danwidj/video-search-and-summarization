// SPDX-License-Identifier: Apache-2.0

import { createReadStream } from 'node:fs';

import { NextResponse } from 'next/server';

import { getAnalysisJobs, getDbAdapters } from '@/lib/container';
import { getServiceConfiguration, isR2Configured, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { duplicateResponse } from '@/lib/http/duplicate-response';
import { putR2Video, r2ObjectExists, verifyR2Video } from '@/lib/r2/config';
import { firstFreeName, inspectUploadName, uploadKeyForName } from '@/lib/r2/names';
import { TranscodeError, prepareUpload } from '@/lib/video/transcode';
import { sha256OfBlob } from '@/lib/uploads-hash';
import { findDuplicateUpload } from '@/modules/jobs/application';
import { DuplicateUploadError } from '@/modules/uploads/domain/duplicate';

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
 * ffmpeg ran or the file was stored byte for byte. `contentSha256` is the hash of
 * the file as uploaded, which the analysis job carries to the video row. A file
 * whose content is already a video in the library, or a queued job, is answered
 * with HTTP 409 and the existing video, before anything is stored.
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

    // The content is checked before anything is converted or stored. It is hashed as uploaded, so a file
    // that is converted to H.264 keeps the hash of the original, whose bytes the reviewer picks again.
    const contentSha256 = await sha256OfBlob(file);
    if (isSupabaseConfigured(config)) {
      const db = getDbAdapters(config);
      const duplicate = await findDuplicateUpload(getAnalysisJobs(config), db.videos, contentSha256);
      if (duplicate) return duplicateResponse(new DuplicateUploadError(duplicate));
    }

    const prepared = await prepareUpload(file);
    try {
      const checked = inspectUploadName(filename);
      const name = await firstFreeName(checked.name, (candidate) => r2ObjectExists(config, uploadKeyForName(candidate)));
      const key = uploadKeyForName(name);
      await putR2Video(config, key, createReadStream(prepared.path), 'video/mp4', prepared.size);
      await verifyR2Video(config, key, prepared.size);
      return NextResponse.json({ filePath: key, name, converted: prepared.converted, contentSha256 });
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
