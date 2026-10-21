// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { errorResponse, rejectionResponse } from '@/lib/http';

// Explicit official-report selection (D6). Only a reviewer action sets or
// clears it; analysis never does, and it is independent of review status.
// The store refuses a run that is not a successful analysis of this video (422).

const selectSchema = z.object({ modelRunId: z.string().min(1).max(20), selectedBy: z.string().trim().min(1).max(256) }).strict();
const clearSchema = z.object({ clearedBy: z.string().trim().min(1).max(256) }).strict();

export async function PUT(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = selectSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'modelRunId and selectedBy are required' }, { status: 400 });
    const result = await getDbAdapters().videos.selectOfficialRun(videoId, parsed.data.modelRunId, parsed.data.selectedBy);
    return NextResponse.json({ official: result });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not select the official report');
  }
}

export async function DELETE(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = clearSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'clearedBy is required' }, { status: 400 });
    const result = await getDbAdapters().videos.clearOfficialRun(videoId, parsed.data.clearedBy);
    return NextResponse.json({ official: result });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not clear the official report');
  }
}
