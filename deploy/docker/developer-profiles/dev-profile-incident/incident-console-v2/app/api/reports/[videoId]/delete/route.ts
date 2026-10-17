// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { deleteReport } from '@/lib/application/reports';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';

export async function DELETE(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const params = new URL(request.url).searchParams;
    const modelRunId = params.get('run');
    if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });
    const config = getServiceConfiguration();
    await deleteReport(getDbAdapters(config), { videoId, modelRunId }, params.get('deleteVideo') === 'true', (storageKey) => Promise.all([
      deleteR2Video(config, storageKey),
      deleteR2Video(config, thumbnailKeyForVideo(storageKey)),
    ]));
    return NextResponse.json({ deleted: true });
  } catch (error) {
    return errorResponse(error, 'Could not delete report');
  }
}
