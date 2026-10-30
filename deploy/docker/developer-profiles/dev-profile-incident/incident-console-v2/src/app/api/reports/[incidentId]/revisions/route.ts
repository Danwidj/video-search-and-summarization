// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { listRevisions } from '@/modules/reports/application/list-revisions';
import { errorResponse } from '@/lib/http';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';

export const dynamic = 'force-dynamic';

/** The incident's versions, newest first, each with its coverage verdict. */
export async function GET(_request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive whole number' }, { status: 400 });
    const revisions = await listRevisions(getDbAdapters().incidentReports, incidentId);
    return NextResponse.json({ revisions });
  } catch (error) {
    return errorResponse(error, 'Could not load the revision history');
  }
}
