// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { changeReviewStatus } from '@/lib/application/reports';
import { errorResponse, rejectionResponse } from '@/lib/http';
import type { ReviewStatus } from '@/lib/reports/storage';

const VALID_STATUSES = new Set<ReviewStatus>(['unreviewed', 'under review', 'verified']);

export async function PATCH(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const input = (await request.json()) as { modelRunId?: string; status?: ReviewStatus; reviewedBy?: string };
    if (!input.modelRunId || !input.status || !VALID_STATUSES.has(input.status)) {
      return NextResponse.json({ error: 'A valid modelRunId and status are required' }, { status: 400 });
    }
    const reviewedBy = input.reviewedBy?.trim();
    if (!reviewedBy) return NextResponse.json({ error: 'Reviewer name is required' }, { status: 400 });
    const { incidents } = getDbAdapters();
    const change = await changeReviewStatus(incidents, { videoId, modelRunId: input.modelRunId }, input.status, reviewedBy);
    if (change.kind === 'not-found') return NextResponse.json({ error: 'Incident not found' }, { status: 404 });
    if (change.kind === 'unchanged') return NextResponse.json({ status: input.status, reviewedBy });
    return NextResponse.json({ status: input.status, reviewedBy, reviewedAt: change.at });
  } catch (error) {
    // e.g. verifying a legacy AI report that must be edited first: 422 with the store's reason.
    return rejectionResponse(error) ?? errorResponse(error, 'Could not update review status');
  }
}
