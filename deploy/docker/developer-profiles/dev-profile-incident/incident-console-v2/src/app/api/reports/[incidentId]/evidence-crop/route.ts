// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getIncidentVideos } from '@/lib/container';
import { incidentVideoLookup } from '@/lib/incident-route';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';
import { cropEvidenceFrame } from '@/lib/application/evidence-frames';
import { FrameRequestError } from '@/lib/evidence/frame-request';
import { errorResponse } from '@/lib/http';
import { r2FrameConfiguration, r2FrameSource } from '@/lib/r2/frame-source';

export const maxDuration = 30;

/**
 * Crops a reviewer-drawn rectangle out of the video frame at a second and
 * answers the JPEG bytes. Body: {video, timestampSeconds, region: {x, y, w, h}}, video being the name of one of
 * the incident's videos, with
 * the region as fractions (0-1) of the frame. Nothing is written to R2: the
 * browser holds the crop, and Save uploads it through /evidence-image.
 */
export async function POST(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    if (!body || typeof body !== 'object')
      return NextResponse.json({ error: 'A JSON body with video, timestampSeconds and region is required' }, { status: 400 });
    if (typeof body.video !== 'string' || !body.video.trim()) return NextResponse.json({ error: 'video is required' }, { status: 400 });
    const config = r2FrameConfiguration();
    const videos = incidentVideoLookup(getIncidentVideos(config), incidentId);
    const jpeg = await cropEvidenceFrame({ videos, source: r2FrameSource(config) }, body.video.trim(), {
      timestampSeconds: body.timestampSeconds,
      region: body.region,
    });
    return new NextResponse(new Uint8Array(jpeg), { headers: { 'content-type': 'image/jpeg', 'cache-control': 'no-store' } });
  } catch (error) {
    if (error instanceof FrameRequestError) return NextResponse.json({ error: error.message }, { status: error.status });
    return errorResponse(error, 'Could not crop the evidence image');
  }
}
