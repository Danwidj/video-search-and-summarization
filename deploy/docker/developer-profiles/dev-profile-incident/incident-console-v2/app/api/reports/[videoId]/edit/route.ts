// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { StructuredEditError, validateStructuredEdit } from '@/lib/contract/structured-edit';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

// Structured (Class A) reviewer edits. The edit replaces the run's relational
// projection atomically through apply_structured_report_edit; model_runs.notes
// (original model output, raw response, repair record, outcome) is never read
// for writing or modified. Class B model output and Class C provenance are
// rejected before anything reaches the database.
const requestSchema = z.object({
  modelRunId: z.string().min(1),
  editedBy: z.string().trim().min(1).max(256),
  edit: z.unknown(),
}).strict();

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      return NextResponse.json({ error: 'The request must contain modelRunId, editedBy and edit only' }, { status: 400 });
    }
    const { modelRunId, editedBy } = parsed.data;
    let edit;
    try {
      edit = validateStructuredEdit(parsed.data.edit);
    } catch (error) {
      if (error instanceof StructuredEditError) {
        return NextResponse.json({ error: error.message, violations: error.violations, notEditable: error.notEditable }, { status: error.status });
      }
      throw error;
    }

    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const incident = await db.selectOne('incidents', { incident_id: videoId, model_run_id: modelRunId }, 'incident_id');
    if (!incident) return NextResponse.json({ error: 'Report not found' }, { status: 404 });

    const result = await db.rpc('apply_structured_report_edit', {
      p_incident_id: videoId,
      p_model_run_id: modelRunId,
      p_edit: edit,
      p_edited_by: editedBy,
    });
    return NextResponse.json({ saved: true, result });
  } catch (error) {
    return errorResponse(error, 'Could not save the edit');
  }
}
