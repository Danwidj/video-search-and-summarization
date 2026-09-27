// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { deleteR2Video } from '@/lib/r2/config';
import { thumbnailKeyForVideo } from '@/lib/r2/key';
import { parseRunNotes } from '@/lib/reports/run-notes';

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
      await deleteFailedAttempts(db, videoId);
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

/**
 * Remove the video's contract_failed / request_failed attempt records. Only
 * records whose notes explicitly name this exact videoId (and that have no
 * incident, so no report) are deleted; the text search is just a pre-filter
 * and every candidate is re-checked from its parsed notes.
 */
async function deleteFailedAttempts(db: PostgrestClient, videoId: string): Promise<void> {
  const candidates = await db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,notes');
  for (const candidate of candidates) {
    const notes = parseRunNotes(candidate.notes);
    if (notes.kind !== 'failed-attempt' || notes.videoId !== videoId || typeof candidate.id !== 'string') continue;
    const incident = await db.selectOne('incidents', { model_run_id: candidate.id }, 'incident_id');
    if (incident) continue;
    await db.deleteWhere('model_runs', { id: candidate.id });
  }
}
