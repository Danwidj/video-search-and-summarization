// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from 'node:crypto';
import { Readable } from 'node:stream';

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { putR2Video, verifyR2Video } from '@/lib/r2/config';
import { uploadedEvidenceKey } from '@/modules/reports/domain/revision';

export const maxDuration = 30;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
// Stored under a .jpg key; the content type is the file's own.
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const ITEM_ID = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * Stores a replacement evidence image under a new, unique R2 key
 * (evidence/<videoId>/<uuid>/<itemId>.jpg). It never overwrites an object, and
 * nothing deletes one here: any revision may still reference it. Only the evidence-sweep route removes an image, and only one no revision names. The key is saved
 * into the next human revision's evidence by Save.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const form = await request.formData();
    const file = form.get('file');
    const itemId = form.get('itemId');
    if (!(file instanceof Blob) || typeof itemId !== 'string' || !ITEM_ID.test(itemId)) {
      return NextResponse.json({ error: 'file and a valid itemId are required' }, { status: 400 });
    }
    if (!IMAGE_TYPES.has(file.type)) return NextResponse.json({ error: 'The image must be JPEG, PNG or WebP' }, { status: 415 });
    if (file.size <= 0 || file.size > MAX_IMAGE_BYTES)
      return NextResponse.json({ error: 'The image must be between 1 byte and 5 MB' }, { status: 413 });

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const key = uploadedEvidenceKey(videoId, randomUUID(), itemId);
    const body = Readable.fromWeb(file.stream() as Parameters<typeof Readable.fromWeb>[0]);
    await putR2Video(config, key, body, file.type, file.size);
    await verifyR2Video(config, key, file.size);
    return NextResponse.json({ image: key });
  } catch (error) {
    return errorResponse(error, 'Could not upload the evidence image');
  }
}
