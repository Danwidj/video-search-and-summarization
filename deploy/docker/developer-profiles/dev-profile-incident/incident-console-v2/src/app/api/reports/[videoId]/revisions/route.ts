// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { listRevisions } from '@/modules/reports/application/reports';
import { errorResponse } from '@/lib/http';

export const dynamic = 'force-dynamic';

/** The incident's History: every revision, newest first. */
export async function GET(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const revisions = await listRevisions(getDbAdapters().incidents, videoId);
    return NextResponse.json({ revisions });
  } catch (error) {
    return errorResponse(error, 'Could not load the revision history');
  }
}
