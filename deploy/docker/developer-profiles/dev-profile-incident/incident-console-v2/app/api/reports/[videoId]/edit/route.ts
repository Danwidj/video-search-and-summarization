// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { StructuredEditError, validateStructuredEdit } from '@/lib/contract/structured-edit';
import { errorResponse } from '@/lib/http';

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

    const { incidents } = getDbAdapters();
    const key = { videoId, modelRunId };
    if (!(await incidents.runExists(key))) return NextResponse.json({ error: 'Report not found' }, { status: 404 });

    const result = await incidents.applyStructuredEdit(key, edit, editedBy);
    return NextResponse.json({ saved: true, result });
  } catch (error) {
    return errorResponse(error, 'Could not save the edit');
  }
}
