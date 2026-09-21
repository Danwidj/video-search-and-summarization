// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  try {
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const filters = new URL(request.url).searchParams.get('unread') === 'true' ? { acknowledged: 'false' } : undefined;
    const notifications = await db.selectMany('notifications', { filters, order: 'created_at.desc', limit: 100 });
    return NextResponse.json({ notifications });
  } catch (error) { return errorResponse(error, 'Could not load notifications'); }
}

export async function PATCH(request: Request) {
  try {
    const input = (await request.json()) as { id?: number; all?: boolean };
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    if (input.all) await db.updateWhere('notifications', { acknowledged: 'false' }, { acknowledged: true });
    else if (typeof input.id === 'number') await db.updateWhere('notifications', { id: String(input.id) }, { acknowledged: true });
    else return NextResponse.json({ error: 'Notification id or all=true is required' }, { status: 400 });
    return NextResponse.json({ acknowledged: true });
  } catch (error) { return errorResponse(error, 'Could not acknowledge notification'); }
}
