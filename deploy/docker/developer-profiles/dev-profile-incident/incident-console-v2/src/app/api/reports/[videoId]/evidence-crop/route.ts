// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from 'node:crypto';

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { createEvidenceCrop } from '@/lib/application/evidence-frames';
import { FrameRequestError } from '@/lib/evidence/frame-request';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { r2EvidenceImageStore, r2FrameConfiguration, r2FrameSource } from '@/lib/r2/frame-source';

export const maxDuration = 30;

/**
 * Crops a reviewer-drawn rectangle out of the video frame at a second and
 * stores it under a new, unique R2 key (evidence/<videoId>/<uuid>/<itemId>.jpg).
 * Body: {itemId, timestampSeconds, region: {x, y, w, h}} with the region as
 * fractions (0-1) of the frame. It never overwrites an object, and nothing
 * deletes one: any revision may still reference it. The key is saved into the
 * next human revision's evidence by Save, like an uploaded image. Answers
 * {image, imageUrl, timestampSeconds, region}; imageUrl is a one-hour signed URL.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body !== 'object') return NextResponse.json({ error: 'A JSON body with itemId, timestampSeconds and region is required' }, { status: 400 });
    const config = r2FrameConfiguration();
    const crop = await createEvidenceCrop(
      { videos: getDbAdapters(config).videos, source: r2FrameSource(config), store: r2EvidenceImageStore(config), newUuid: randomUUID },
      videoId,
      { itemId: body.itemId, timestampSeconds: body.timestampSeconds, region: body.region },
    );
    const imageUrl = await createR2PlaybackUrl(config, crop.image);
    return NextResponse.json({ image: crop.image, imageUrl, timestampSeconds: crop.timestampSeconds, region: crop.region });
  } catch (error) {
    if (error instanceof FrameRequestError) return NextResponse.json({ error: error.message }, { status: error.status });
    return errorResponse(error, 'Could not crop the evidence image');
  }
}
