// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { cropEvidenceFrame } from '@/lib/application/evidence-frames';
import { FrameRequestError } from '@/lib/evidence/frame-request';
import { errorResponse } from '@/lib/http';
import { r2FrameConfiguration, r2FrameSource } from '@/lib/r2/frame-source';

export const maxDuration = 30;

/**
 * Crops a reviewer-drawn rectangle out of the video frame at a second and
 * answers the JPEG bytes. Body: {timestampSeconds, region: {x, y, w, h}} with
 * the region as fractions (0-1) of the frame. Nothing is written to R2: the
 * browser holds the crop, and Save uploads it through /evidence-image.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body !== 'object') return NextResponse.json({ error: 'A JSON body with timestampSeconds and region is required' }, { status: 400 });
    const config = r2FrameConfiguration();
    const jpeg = await cropEvidenceFrame(
      { videos: getDbAdapters(config).videos, source: r2FrameSource(config) },
      videoId,
      { timestampSeconds: body.timestampSeconds, region: body.region },
    );
    return new NextResponse(new Uint8Array(jpeg), { headers: { 'content-type': 'image/jpeg', 'cache-control': 'no-store' } });
  } catch (error) {
    if (error instanceof FrameRequestError) return NextResponse.json({ error: error.message }, { status: error.status });
    return errorResponse(error, 'Could not crop the evidence image');
  }
}
