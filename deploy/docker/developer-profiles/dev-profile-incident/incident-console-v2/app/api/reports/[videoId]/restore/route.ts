// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/adapters/supabase';
import { restoreRevision } from '@/lib/application/reports';
import { errorResponse, rejectionResponse } from '@/lib/http';

// Restore: a new human revision with the content of an earlier one. Nothing
// is changed or deleted; the restored revision is the new one's parent.
const requestSchema = z.object({
  revisionId: z.number().int().positive(),
  restoredBy: z.string().trim().min(1).max(256),
}).strict();

export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'revisionId and restoredBy are required' }, { status: 400 });
    const revision = await restoreRevision(getDbAdapters().incidents, { videoId, revisionId: parsed.data.revisionId, createdBy: parsed.data.restoredBy });
    return NextResponse.json({ restored: true, revision });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not restore the revision');
  }
}
