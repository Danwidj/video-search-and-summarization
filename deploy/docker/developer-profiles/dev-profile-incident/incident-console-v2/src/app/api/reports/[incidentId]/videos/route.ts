// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { errorResponse } from '@/lib/http';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';

export const dynamic = 'force-dynamic';

// The names of the incident's videos and whether it has an official version: what the merge dialog shows of the incident
// it merges into. Read only.
export async function GET(_request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const id = parseIncidentId((await context.params).incidentId);
    if (id === null) return NextResponse.json({ error: 'The incident id must be a positive whole number' }, { status: 400 });
    const side = await getDbAdapters().incidentReports.getSideSummary(id);
    if (!side) return NextResponse.json({ error: `Incident ${id} does not exist` }, { status: 404 });
    return NextResponse.json({ videoNames: side.videoNames, hasOfficial: side.hasOfficial });
  } catch (error) {
    return errorResponse(error, 'Could not read the incident');
  }
}
