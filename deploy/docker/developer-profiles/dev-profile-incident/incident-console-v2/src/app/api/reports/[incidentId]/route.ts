// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getReport } from '@/modules/reports/application/get-report';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';

export const dynamic = 'force-dynamic';

/**
 * One revision of the incident's report: ?revision=<id>, else the official revision, else the newest; ?camera=<video name>
 * picks the camera, else the first one that can be shown. The body carries the overview, the coverage verdict, the cameras
 * and that camera's report.
 */
export async function GET(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive whole number' }, { status: 400 });
    const params = new URL(request.url).searchParams;
    const raw = params.get('revision');
    const revisionId = raw === null ? null : Number(raw);
    if (revisionId !== null && (!Number.isSafeInteger(revisionId) || revisionId < 1)) {
      return NextResponse.json({ error: 'The revision must be a positive whole number' }, { status: 400 });
    }
    const camera = params.get('camera')?.trim() || null;

    const config = getServiceConfiguration();
    const { incidentReports } = getDbAdapters(config);
    const report = await getReport(incidentReports, incidentId, revisionId, camera, (storageKey) =>
      createR2PlaybackUrl(config, storageKey),
    );
    if (!report) {
      // An incident that has videos but no version yet (waiting for a match decision or a build) is not "not found":
      // the page shows its videos and what it is waiting for.
      const incident = await incidentReports.getIncident(incidentId);
      if (incident && incident.revisions.length === 0) {
        const videos = await Promise.all(
          incident.videos.map(async (video) => ({
            name: video.videoId,
            playbackUrl: video.storageKey ? await createR2PlaybackUrl(config, video.storageKey).catch(() => null) : null,
          })),
        );
        return NextResponse.json({ error: 'This incident has no report yet', waiting: { videos } }, { status: 404 });
      }
      return NextResponse.json({ error: 'Report not found' }, { status: 404 });
    }
    return NextResponse.json({ report });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not load the report');
  }
}
