// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters, getRemoveVstSensor } from '@/lib/container';
import { deleteVideoAndReports } from '@/modules/reports/application/delete-video-and-reports';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';
import { R2EvidenceObjectStore } from '@/modules/reports/infrastructure/r2/evidence-object-store';

// Revisions are append-only, so the only delete is the whole video and every
// revision of it, with its VST camera and its video, thumbnail and evidence images in R2.
export async function DELETE(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const config = getServiceConfiguration();
    await deleteVideoAndReports(
      getDbAdapters(config).videos,
      new R2EvidenceObjectStore(config),
      videoId,
      (storageKey: string) => Promise.all([deleteR2Video(config, storageKey), deleteR2Video(config, thumbnailKeyForVideo(storageKey))]),
      getRemoveVstSensor(config),
    );
    return NextResponse.json({ deleted: true });
  } catch (error) {
    return errorResponse(error, 'Could not delete the video');
  }
}
