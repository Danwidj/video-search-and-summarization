// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getIncidentVideos } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';
import { deleteIncident } from '@/modules/reports/application/delete-incident';
import { R2EvidenceObjectStore } from '@/modules/reports/infrastructure/r2/evidence-object-store';
import { removeVstSensor } from '@/modules/videos/infrastructure/vst/sensor';

export const maxDuration = 60;

// Deletes the incident: each of its videos with its video object, thumbnail and evidence images in
// R2 (under the R2 key prefix), then the incident with its revisions and crops.
export async function DELETE(_request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const { incidentId } = await context.params;
    const id = Number(incidentId);
    if (!Number.isSafeInteger(id) || id <= 0)
      return NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });
    const config = getServiceConfiguration();
    const result = await deleteIncident(
      {
        videos: getIncidentVideos(config),
        evidence: new R2EvidenceObjectStore(config),
        removeStoredVideo: (storageKey: string) =>
          Promise.all([deleteR2Video(config, storageKey), deleteR2Video(config, thumbnailKeyForVideo(storageKey))]),
        removeVstSensor: (video) => removeVstSensor(config, video),
      },
      id,
    );
    return NextResponse.json({ deleted: true, ...result });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not delete the incident');
  }
}
