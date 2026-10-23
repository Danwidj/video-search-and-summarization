// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { saveHumanEdit } from '@/lib/application/reports';
import { StructuredEditError, validateStructuredEdit } from '@/lib/contract/structured-edit';
import { errorResponse, rejectionResponse } from '@/lib/http';

// Save: structured (Class A) reviewer edits become a new human revision whose
// parent is the revision the reviewer opened (parentId). Earlier revisions and
// model_runs.notes (original model output, raw response, repair record,
// outcome) are never modified. Class B model output and Class C provenance are
// rejected before anything reaches the database.
const requestSchema = z.object({
  parentId: z.number().int().positive(),
  editedBy: z.string().trim().min(1).max(256),
  note: z.string().trim().max(2000).nullish(),
  edit: z.unknown(),
}).strict();

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      return NextResponse.json({ error: 'The request must contain parentId, editedBy, edit and optionally note only' }, { status: 400 });
    }
    let edit;
    try {
      edit = validateStructuredEdit(parsed.data.edit);
    } catch (error) {
      if (error instanceof StructuredEditError) {
        return NextResponse.json({ error: error.message, violations: error.violations, notEditable: error.notEditable }, { status: error.status });
      }
      throw error;
    }

    const revision = await saveHumanEdit(getDbAdapters().incidents, { videoId, parentId: parsed.data.parentId, edit, createdBy: parsed.data.editedBy, note: parsed.data.note });
    return NextResponse.json({ saved: true, revision });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not save the edit');
  }
}
