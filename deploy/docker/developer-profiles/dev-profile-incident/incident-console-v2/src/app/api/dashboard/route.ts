// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { errorResponse } from '@/lib/http';
import type { DashboardSeverity } from '@/modules/dashboard/domain/DashboardRepository';
import { isValidTimeZone, parseStoredTimestamp } from '@/lib/time';

export const dynamic = 'force-dynamic';

const PERIODS = new Set(['7', '30', 'all']);
const SEVERITIES = new Set(['low', 'medium', 'high']);
const isSeverity = (value: string): value is DashboardSeverity => SEVERITIES.has(value);

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
    const severity = params.get('severity') || null;
    const tzParam = params.get('timezone');
    if (tzParam !== null && !isValidTimeZone(tzParam)) return NextResponse.json({ error: 'Invalid dashboard timezone' }, { status: 400 });
    const timezone = tzParam || 'UTC';
    if (!PERIODS.has(period)) return NextResponse.json({ error: 'Invalid dashboard period' }, { status: 400 });
    if (severity !== null && !isSeverity(severity)) return NextResponse.json({ error: 'Invalid severity filter' }, { status: 400 });

    const { dashboard } = getDbAdapters();
    const requestedStart = params.get('after');
    const requestedEnd = params.get('before');
    // after/before are zoneless UTC (like every stored timestamp); read them as UTC, never as server-local time.
    const periodEnd = period === 'all' ? null : requestedEnd ? (parseStoredTimestamp(requestedEnd) ?? new Date(NaN)) : new Date();
    const periodStart = periodEnd
      ? requestedStart
        ? (parseStoredTimestamp(requestedStart) ?? new Date(NaN))
        : new Date(periodEnd.getTime() - Number(period) * 86_400_000)
      : null;
    if (
      (periodStart && Number.isNaN(periodStart.getTime())) ||
      (periodEnd && Number.isNaN(periodEnd.getTime())) ||
      (periodStart && periodEnd && periodStart >= periodEnd)
    ) {
      return NextResponse.json({ error: 'Invalid dashboard date range' }, { status: 400 });
    }
    const analytics = await dashboard.getDashboard({
      periodStart,
      periodEnd,
      type: params.get('type')?.trim() || null,
      severity,
      dayOfWeek: integerParameter(params, 'day', 0, 6),
      hour: integerParameter(params, 'hour', 0, 23),
      timezone,
    });
    return NextResponse.json({ analytics });
  } catch (error) {
    if (error instanceof RangeError) return NextResponse.json({ error: error.message }, { status: 400 });
    return errorResponse(error, 'Could not load dashboard analytics');
  }
}
