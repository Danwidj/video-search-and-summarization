// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getIncidentVideos } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';
import { removeVideoFromIncident } from '@/modules/reports/application/remove-video';
import { R2EvidenceObjectStore } from '@/modules/reports/infrastructure/r2/evidence-object-store';

export const maxDuration = 60;

const requestSchema = z.object({ choice: z.enum(['delete', 'move']) }).strict();

// Removes a video from its incident: 'delete' removes it entirely (its objects under the R2 key
// prefix too, and the incident when it was the last video); 'move' makes it an incident of its own
// and moves no file. The caller then builds the new incident's first report.
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: "choice must be 'delete' or 'move'" }, { status: 400 });
    const config = getServiceConfiguration();
    const result = await removeVideoFromIncident(
      {
        videos: getIncidentVideos(config),
        evidence: new R2EvidenceObjectStore(config),
        removeStoredVideo: (storageKey: string) =>
          Promise.all([deleteR2Video(config, storageKey), deleteR2Video(config, thumbnailKeyForVideo(storageKey))]),
      },
      videoId,
      parsed.data.choice,
    );
    return NextResponse.json({ removed: result });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not remove the video');
  }
}
