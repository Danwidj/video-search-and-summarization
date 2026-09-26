// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';

export async function DELETE(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const params = new URL(request.url).searchParams;
    const modelRunId = params.get('run');
    if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    if (params.get('deleteVideo') === 'true') {
      const video = await db.selectOne('videos', { id: videoId });
      if (typeof video?.filepath !== 'string') throw new Error('Video has no R2 object key');
      await Promise.all([
        deleteR2Video(config, video.filepath),
        deleteR2Video(config, thumbnailKeyForVideo(video.filepath)),
      ]);
      await db.deleteWhere('videos', { id: videoId });
    } else {
      await db.deleteWhere('incidents', { incident_id: videoId, model_run_id: modelRunId });
    }
    return NextResponse.json({ deleted: true });
  } catch (error) {
    return errorResponse(error, 'Could not delete report');
  }
}
