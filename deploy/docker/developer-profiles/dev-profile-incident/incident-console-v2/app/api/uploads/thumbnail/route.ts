// SPDX-License-Identifier: Apache-2.0

import { Readable } from 'node:stream';

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { putR2Video, verifyR2Video } from '@/lib/r2/config';
import { isValidR2Key, thumbnailKeyForVideo } from '@/lib/r2/key';

export const maxDuration = 30;
const MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024;
const IMAGE_TYPES = new Set(['image/webp', 'image/jpeg', 'image/png']);

export async function POST(request: Request) {
  try {
    const form = await request.formData();
    const file = form.get('file');
    const videoKey = form.get('videoKey');
    if (!(file instanceof Blob) || !isValidR2Key(videoKey)) {
      return NextResponse.json({ error: 'file and a valid videoKey are required' }, { status: 400 });
    }
    if (!IMAGE_TYPES.has(file.type)) {
      return NextResponse.json({ error: 'Thumbnail must be WebP, JPEG, or PNG' }, { status: 415 });
    }
    if (file.size <= 0 || file.size > MAX_THUMBNAIL_BYTES) {
      return NextResponse.json({ error: 'Thumbnail must be between 1 byte and 2 MB' }, { status: 413 });
    }

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const thumbnailKey = thumbnailKeyForVideo(videoKey);
    const body = Readable.fromWeb(file.stream() as Parameters<typeof Readable.fromWeb>[0]);
    await putR2Video(config, thumbnailKey, body, file.type, file.size);
    await verifyR2Video(config, thumbnailKey, file.size);
    return NextResponse.json({ thumbnailKey });
  } catch (error) {
    return errorResponse(error, 'Could not upload the video thumbnail');
  }
}
