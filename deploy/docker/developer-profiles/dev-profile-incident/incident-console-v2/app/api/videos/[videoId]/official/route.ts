// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

// Explicit official-report selection (D6). Only a reviewer action sets or
// clears it; analysis never does, and it is independent of review status.

const selectSchema = z.object({ modelRunId: z.string().min(1).max(20), selectedBy: z.string().trim().min(1).max(256) }).strict();
const clearSchema = z.object({ clearedBy: z.string().trim().min(1).max(256) }).strict();

function database() {
  const config = getServiceConfiguration();
  if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
  return new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
}

/** The database refuses a run that is not a successful analysis of this video; surface that as 422. */
function rejection(error: unknown): NextResponse | null {
  const message = error instanceof Error ? error.message : '';
  const match = /"message":"([^"]+)"/.exec(message);
  if (match && /official report|reviewer name|Video not found/.test(match[1])) {
    return NextResponse.json({ error: match[1] }, { status: /Video not found/.test(match[1]) ? 404 : 422 });
  }
  return null;
}

export async function PUT(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = selectSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'modelRunId and selectedBy are required' }, { status: 400 });
    const result = await database().rpc('select_official_report', { p_video_id: videoId, p_model_run_id: parsed.data.modelRunId, p_selected_by: parsed.data.selectedBy });
    return NextResponse.json({ official: result });
  } catch (error) {
    return rejection(error) ?? errorResponse(error, 'Could not select the official report');
  }
}

export async function DELETE(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = clearSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'clearedBy is required' }, { status: 400 });
    const result = await database().rpc('clear_official_report', { p_video_id: videoId, p_cleared_by: parsed.data.clearedBy });
    return NextResponse.json({ official: result });
  } catch (error) {
    return rejection(error) ?? errorResponse(error, 'Could not clear the official report');
  }
}
