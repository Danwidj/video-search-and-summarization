// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { ContractError, validateContractReport } from '@/lib/analysis/contract';
import { incidentColumns } from '@/lib/analysis/persistence';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

const editSchema = z.object({
  modelRunId: z.string().min(1),
  editedReport: z.unknown(),
});

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const input = editSchema.parse(await request.json());

    // Reviewer edits follow the same contract as model output; duration is recomputed from the times.
    let edited;
    try {
      edited = validateContractReport(input.editedReport);
    } catch (error) {
      if (error instanceof ContractError) {
        return NextResponse.json({ error: `The edited report does not match the incident contract: ${error.message}` }, { status: 400 });
      }
      throw error;
    }

    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const run = await db.selectOne('model_runs', { id: input.modelRunId });
    if (!run) throw new Error('Model run not found');
    const incident = await db.selectOne('incidents', { incident_id: videoId, model_run_id: input.modelRunId });
    if (!incident) throw new Error('Report not found for this video and model run');

    let notes: Record<string, unknown> = {};
    try {
      const parsed = typeof run.notes === 'string' ? JSON.parse(run.notes) as Record<string, unknown> : {};
      notes = parsed && typeof parsed === 'object' ? parsed : {};
    } catch { /* Replace malformed notes with a valid wrapper; the original AI report stays whatever was stored. */ }
    const existing = notes.incidentConsoleV2 && typeof notes.incidentConsoleV2 === 'object'
      ? notes.incidentConsoleV2 as Record<string, unknown>
      : {};
    // The original AI report is never overwritten; only the editable copy changes.
    await db.updateWhere('model_runs', { id: input.modelRunId }, {
      notes: JSON.stringify({ ...notes, incidentConsoleV2: { ...existing, editedReport: edited } }),
    });
    await db.updateWhere(
      'incidents',
      { incident_id: videoId, model_run_id: input.modelRunId },
      incidentColumns(edited),
    );
    await db.updateWhere('review_status', { incident_id: videoId, model_run_id: input.modelRunId }, { edited_at: new Date().toISOString() });
    return NextResponse.json({ saved: true, report: edited });
  } catch (error) {
    return errorResponse(error, 'Could not edit report');
  }
}
