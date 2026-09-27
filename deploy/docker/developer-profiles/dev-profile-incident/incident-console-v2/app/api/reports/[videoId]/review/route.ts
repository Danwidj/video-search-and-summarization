// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
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
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const [incident, currentReview] = await Promise.all([
      db.selectOne('incidents', { incident_id: videoId, model_run_id: input.modelRunId }),
      db.selectOne('review_status', { incident_id: videoId, model_run_id: input.modelRunId }),
    ]);
    if (!incident) return NextResponse.json({ error: 'Incident not found' }, { status: 404 });
    if (currentReview?.status === input.status) {
      return NextResponse.json({ status: input.status, reviewedBy });
    }
    const now = new Date().toISOString();
    await db.upsert('review_status', {
      incident_id: videoId,
      model_run_id: input.modelRunId,
      status: input.status,
      edited_by: reviewedBy,
      edited_at: now,
      verified_by: input.status === 'verified' ? reviewedBy : null,
      verified_at: input.status === 'verified' ? now : null,
    }, 'incident_id,model_run_id');
    return NextResponse.json({ status: input.status, reviewedBy, reviewedAt: now });
  } catch (error) {
    return errorResponse(error, 'Could not update review status');
  }
}
