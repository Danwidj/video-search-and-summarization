// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

const editSchema = z.object({ modelRunId: z.string().min(1), editor: z.string().trim().min(1), incidentType: z.string().trim().min(1).max(32), summary: z.string().trim().min(1), startTimestamp: z.string().nullable(), endTimestamp: z.string().nullable(), severityLevel: z.number().int().min(1).max(5), confidenceScore: z.number().min(0).max(1) });
export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params; const input = editSchema.parse(await request.json());
    const config = getServiceConfiguration(); if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    await db.updateWhere('incidents', { incident_id: videoId, model_run_id: input.modelRunId }, { type: input.incidentType, description: input.summary, start_timestamp: input.startTimestamp, end_timestamp: input.endTimestamp, severity_level: input.severityLevel, confidence_score: input.confidenceScore });
    await db.updateWhere('review_status', { incident_id: videoId, model_run_id: input.modelRunId }, { edited_by: input.editor, edited_at: new Date().toISOString() });
    return NextResponse.json({ saved: true });
  } catch (error) { return errorResponse(error, 'Could not edit report'); }
}
