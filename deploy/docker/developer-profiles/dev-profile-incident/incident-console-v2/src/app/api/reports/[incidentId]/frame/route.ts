// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getVideoFrame } from '@/lib/application/evidence-frames';
import { FrameRequestError } from '@/lib/evidence/frame-request';
import { errorResponse } from '@/lib/http';
import { r2FrameConfiguration, r2FrameSource } from '@/lib/r2/frame-source';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

/**
 * The frame at ?t=<seconds> of one of the incident's videos as a JPEG, for the frame picker. ?video=<file name> names
 * the video (it may be left out when the incident holds just one). 400 for a missing or malformed t, a bad incident id
 * or a missing video name, 422 for a t past the end of the video, 404 for an unknown incident or a video that is not
 * in it, 503 when ffmpeg is not installed on the console host.
 */
export async function GET(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive whole number' }, { status: 400 });
    const params = new URL(request.url).searchParams;
    const config = r2FrameConfiguration();
    const incident = await getDbAdapters(config).incidentReports.getIncident(incidentId);
    if (!incident) return NextResponse.json({ error: 'Incident not found' }, { status: 404 });
    const named = params.get('video')?.trim() || null;
    const videoId = named ?? (incident.videos.length === 1 ? incident.videos[0].videoId : null);
    if (videoId === null) return NextResponse.json({ error: 'The video must be named' }, { status: 400 });
    // Only a video of this incident is read, so the incident id is what covers the frame.
    const jpeg = await getVideoFrame(
      { videos: { getVideo: async (id) => incident.videos.find((video) => video.videoId === id) ?? null }, source: r2FrameSource(config) },
      videoId,
      params.get('t'),
    );
    return new NextResponse(new Uint8Array(jpeg), { headers: { 'Content-Type': 'image/jpeg', 'Cache-Control': 'private, max-age=300' } });
  } catch (error) {
    if (error instanceof FrameRequestError) return NextResponse.json({ error: error.message }, { status: error.status });
    return errorResponse(error, 'Could not read the video frame');
  }
}
