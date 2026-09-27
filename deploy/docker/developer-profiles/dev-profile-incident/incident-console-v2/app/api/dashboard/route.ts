// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import type { DashboardAnalytics } from '@/lib/dashboard/types';

export const dynamic = 'force-dynamic';

const PERIODS = new Set(['7', '30', 'all']);
const SEVERITIES = new Set(['low', 'medium', 'high']);

function integerParameter(params: URLSearchParams, name: string, minimum: number, maximum: number): number | null {
  const raw = params.get(name);
  if (raw === null) return null;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < minimum || value > maximum) throw new RangeError(`Invalid ${name} filter`);
  return value;
}

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const period = params.get('days') || '30';
    const severity = params.get('severity');
    if (!PERIODS.has(period)) return NextResponse.json({ error: 'Invalid dashboard period' }, { status: 400 });
    if (severity && !SEVERITIES.has(severity)) return NextResponse.json({ error: 'Invalid severity filter' }, { status: 400 });

    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const requestedStart = params.get('after');
    const requestedEnd = params.get('before');
    const periodEnd = period === 'all' ? null : requestedEnd ? new Date(requestedEnd) : new Date();
    const periodStart = periodEnd ? requestedStart ? new Date(requestedStart) : new Date(periodEnd.getTime() - Number(period) * 86_400_000) : null;
    if ((periodStart && Number.isNaN(periodStart.getTime())) || (periodEnd && Number.isNaN(periodEnd.getTime())) || (periodStart && periodEnd && periodStart >= periodEnd)) {
      return NextResponse.json({ error: 'Invalid dashboard date range' }, { status: 400 });
    }
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const analytics = await db.rpc('get_incident_dashboard', {
      p_period_start: periodStart?.toISOString().replace('Z', '') ?? null,
      p_period_end: periodEnd?.toISOString().replace('Z', '') ?? null,
      p_type: params.get('type')?.trim() || null,
      p_severity: severity || null,
      p_day_of_week: integerParameter(params, 'day', 0, 6),
      p_hour: integerParameter(params, 'hour', 0, 23),
    }) as DashboardAnalytics;
    return NextResponse.json({ analytics });
  } catch (error) {
    if (error instanceof RangeError) return NextResponse.json({ error: error.message }, { status: 400 });
    return errorResponse(error, 'Could not load dashboard analytics');
  }
}
