// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { incidentAnalysisSchema } from '@/lib/analysis/schema';

const editSchema = z.object({
  modelRunId: z.string().min(1),
  originalReport: z.unknown(),
  editedReport: z.unknown(),
});

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const input = editSchema.parse(await request.json());
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const original = incidentAnalysisSchema.parse(input.originalReport);
    const edited = incidentAnalysisSchema.parse(input.editedReport);
    const patch = Object.fromEntries(
      Object.entries(edited).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key as keyof typeof original])),
    );
    if (Object.keys(patch).length === 0) return NextResponse.json({ saved: true, unchanged: true });
    const saved = await db.rpc('apply_incident_report_patch', {
      p_incident_id: videoId,
      p_model_run_id: input.modelRunId,
      p_original_report: original,
      p_report_patch: patch,
    });
    return NextResponse.json({ saved: true, report: saved });
  } catch (error) {
    return errorResponse(error, 'Could not edit report');
  }
}
