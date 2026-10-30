// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';
import { fetchEvidenceItemEmbeddings } from '@/modules/reports/infrastructure/agent/evidence-embeddings';
import { SearchableStepError } from '@/modules/reports/application/save-human-edit';
import { saveIncidentHumanEdit, type IncidentEditTarget } from '@/modules/reports/application/save-human-edit/incident';
import { StructuredEditError, validateStructuredEdit } from '@/modules/contract/domain/structured-edit';
import type { StructuredEdit } from '@/modules/reports/domain/edit-draft';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';

// Save: a reviewer's edit of one camera (camera + edit) or of the overview (overview) becomes a new human
// revision of the whole report. Its parent is the revision the reviewer opened (parentId) and it takes the
// parent's coverage. For a camera, structured (Class A) edits only: Class B model output and Class C provenance
// are rejected before anything reaches the database. Earlier revisions and model_runs.notes are never modified.
const overviewSchema = z
  .object({
    title: z.string().trim().max(500).nullish(),
    type: z.string().trim().max(200).nullish(),
    severity_level: z.number().int().min(1).max(5).nullish(),
    description: z.string().trim().max(10_000).nullish(),
    location: z.string().trim().max(500).nullish(),
  })
  .strict();

const requestSchema = z
  .object({
    parentId: z.number().int().positive(),
    editedBy: z.string().trim().min(1).max(256),
    note: z.string().trim().max(2000).nullish(),
    camera: z.string().trim().min(1).max(512).optional(),
    edit: z.unknown().optional(),
    overview: overviewSchema.optional(),
  })
  .strict()
  .refine((body) => (body.camera !== undefined && body.edit !== undefined) !== (body.overview !== undefined), {
    message: 'Give camera and edit, or overview',
  });

export async function PATCH(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      return NextResponse.json(
        { error: 'The request must contain parentId, editedBy, optionally note, and either camera with edit or overview' },
        { status: 400 },
      );
    }
    let target: IncidentEditTarget;
    if (parsed.data.overview !== undefined) {
      target = { overview: parsed.data.overview };
    } else {
      let edit: StructuredEdit;
      try {
        edit = validateStructuredEdit(parsed.data.edit);
      } catch (error) {
        if (error instanceof StructuredEditError) {
          return NextResponse.json(
            { error: error.message, violations: error.violations, notEditable: error.notEditable },
            { status: error.status },
          );
        }
        throw error;
      }
      target = { camera: parsed.data.camera as string, edit };
    }

    const config = getServiceConfiguration();
    // With no official revision the new revision is the searched one: its crops are embedded and written with it.
    const revision = await saveIncidentHumanEdit(
      getDbAdapters(config).incidentReports,
      { incidentId, parentId: parsed.data.parentId, target, createdBy: parsed.data.editedBy, note: parsed.data.note },
      (evidence) => fetchEvidenceItemEmbeddings(config, evidence),
    );
    return NextResponse.json({ saved: true, revision });
  } catch (error) {
    if (error instanceof SearchableStepError) return NextResponse.json({ error: error.message }, { status: 502 });
    return rejectionResponse(error) ?? errorResponse(error, 'Could not save the edit');
  }
}
