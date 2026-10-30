// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { mergeIncidents } from '@/modules/reports/application/merge-incidents';

const requestSchema = z.object({ sourceIncidentId: z.number().int().positive() }).strict();

// Merges the source incident into this one (the target, which is kept). No file moves.
export async function POST(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const { incidentId } = await context.params;
    const target = Number(incidentId);
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!Number.isSafeInteger(target) || target <= 0 || !parsed.success) {
      return NextResponse.json({ error: 'The incident id and sourceIncidentId must be positive integers' }, { status: 400 });
    }
    return NextResponse.json({ merged: await mergeIncidents(getDbAdapters().incidentReports, target, parsed.data.sourceIncidentId) });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not merge the incidents');
  }
}
