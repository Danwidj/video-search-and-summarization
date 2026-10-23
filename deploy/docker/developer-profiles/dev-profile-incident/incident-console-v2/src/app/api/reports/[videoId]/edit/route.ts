// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { fetchEvidenceEmbeddings } from '@/lib/agent/evidence-embeddings';
import { saveHumanEdit, storeSearchableCrops } from '@/lib/application/reports';
import { StructuredEditError, validateStructuredEdit } from '@/modules/contract/domain/structured-edit';
import { getServiceConfiguration } from '@/lib/env';
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

    const config = getServiceConfiguration();
    const adapters = getDbAdapters(config);
    const revision = await saveHumanEdit(adapters.incidents, { videoId, parentId: parsed.data.parentId, edit, createdBy: parsed.data.editedBy, note: parsed.data.note });
    // With no official revision the new revision is the searched one: give it crops now.
    const searchable = await storeSearchableCrops(adapters, videoId, revision.revisionId, (id) => fetchEvidenceEmbeddings(config, id));
    return NextResponse.json({ saved: true, revision, searchable });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not save the edit');
  }
}
