// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

const editSchema = z.object({
  modelRunId: z.string().min(1),
  editor: z.string().trim().min(1),
  incident_type: z.string().trim().min(1).max(32),
  description: z.string().trim().min(1),
  incident_start: z.string().nullable(),
  incident_end: z.string().nullable(),
  severity: z.number().int().min(1).max(5),
  confidence: z.number().min(0).max(1),
});

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const input = editSchema.parse(await request.json());
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    await db.updateWhere(
      'incidents',
      { incident_id: videoId, model_run_id: input.modelRunId },
      {
        type: input.incident_type,
        description: input.description,
        start_timestamp: input.incident_start,
        end_timestamp: input.incident_end,
        severity_level: input.severity,
        confidence_score: input.confidence,
      },
    );
    await db.updateWhere('review_status', { incident_id: videoId, model_run_id: input.modelRunId }, { edited_by: input.editor, edited_at: new Date().toISOString() });
    return NextResponse.json({ saved: true });
  } catch (error) {
    return errorResponse(error, 'Could not edit report');
  }
}
