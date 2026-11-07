// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';

export const dynamic = 'force-dynamic';

/** A signed link to the incident's video, for the Library card's hover preview (the same signing the report page uses). */
export async function GET(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    const record = await incidents.getRevision(videoId, null);
    const key = record?.video.storageKey;
    if (!key) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    const url = await createR2PlaybackUrl(config, key);
    return NextResponse.json({ url }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return errorResponse(error, 'Could not load the video preview');
  }
}
