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
    const run = await db.selectOne('model_runs', { id: input.modelRunId });
    if (!run) throw new Error('Model run not found');
    const incident = await db.selectOne('incidents', { incident_id: videoId, model_run_id: input.modelRunId });
    if (!incident) throw new Error('Report not found for this video and model run');
    const original = incidentAnalysisSchema.parse(input.originalReport);
    const edited = incidentAnalysisSchema.parse(input.editedReport);
    let notes: Record<string, unknown> = {};
    try {
      const parsed = typeof run.notes === 'string' ? JSON.parse(run.notes) as Record<string, unknown> : {};
      notes = parsed && typeof parsed === 'object' ? parsed : {};
    } catch { /* Replace malformed notes with a valid wrapper while retaining the source report below. */ }
    const existing = notes.incidentConsoleV2 && typeof notes.incidentConsoleV2 === 'object'
      ? notes.incidentConsoleV2 as Record<string, unknown>
      : {};
    const originalStored = existing.report && typeof existing.report === 'object' ? existing.report : original;
    await db.updateWhere('model_runs', { id: input.modelRunId }, {
      notes: JSON.stringify({
        ...notes,
        incidentConsoleV2: { ...existing, report: originalStored, editedReport: edited },
      }),
    });
    await db.updateWhere(
      'incidents',
      { incident_id: videoId, model_run_id: input.modelRunId },
      {
        type: edited.incident_type,
        description: edited.description,
        start_timestamp: edited.incident_start,
        end_timestamp: edited.incident_end,
        duration: edited.duration_seconds,
        severity_level: edited.severity,
        confidence_score: edited.confidence,
      },
    );
    await db.rpc('replace_incident_evidence', {
      p_incident_id: videoId,
      p_model_run_id: input.modelRunId,
      p_entities: edited.persons.map((person, index) => ({
        entity_id: `e${String(index + 1).padStart(2, '0')}`,
        type: 'person',
        description: [person.description, person.actions].filter(Boolean).join(' '),
      })),
      p_instruments: edited.instruments.map((item, index) => ({
        instrument_id: `i${String(index + 1).padStart(2, '0')}`,
        name: item.name,
        description: item.description,
        threat_level: item.threat_level,
      })),
      p_assets: edited.assets.map((item, index) => ({
        asset_id: `a${String(index + 1).padStart(2, '0')}`,
        name: item.name,
        description: item.description,
      })),
    });
    await db.updateWhere('review_status', { incident_id: videoId, model_run_id: input.modelRunId }, { edited_at: new Date().toISOString() });
    return NextResponse.json({ saved: true });
  } catch (error) {
    return errorResponse(error, 'Could not edit report');
  }
}
