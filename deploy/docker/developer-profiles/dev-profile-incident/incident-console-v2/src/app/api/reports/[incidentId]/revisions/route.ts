// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { listRevisions } from '@/modules/reports/application/list-revisions';
import { errorResponse } from '@/lib/http';

export const dynamic = 'force-dynamic';

/** The incident's History: every revision, newest first. */
export async function GET(_request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const { incidentId } = await context.params;
    const revisions = await listRevisions(getDbAdapters().incidents, incidentId);
    return NextResponse.json({ revisions });
  } catch (error) {
    return errorResponse(error, 'Could not load the revision history');
  }
}
