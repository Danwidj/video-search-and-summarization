// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { deleteVideoAndReports } from '@/modules/reports/application/reports';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';

// Revisions are append-only, so the only delete is the whole video and every
// revision of it. Evidence images under evidence/<videoId>/ stay in R2.
export async function DELETE(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const config = getServiceConfiguration();
    await deleteVideoAndReports(getDbAdapters(config).videos, videoId, (storageKey: string) => Promise.all([
      deleteR2Video(config, storageKey),
      deleteR2Video(config, thumbnailKeyForVideo(storageKey)),
    ]));
    return NextResponse.json({ deleted: true });
  } catch (error) {
    return errorResponse(error, 'Could not delete the video');
  }
}
