// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key, thumbnailKeyForVideo } from '@/lib/r2/key';
import type { ReportLibraryItem } from '@/lib/reports/storage';

export const dynamic = 'force-dynamic';

const PAGE_SIZE = 6;
const SORTS = new Set(['newest', 'oldest', 'severity-high', 'severity-low', 'confidence-high', 'confidence-low']);
const SEVERITIES = new Set(['all', 'low', 'medium', 'high', '1', '2', '3', '4', '5']);

interface RpcResult {
  reports?: ReportLibraryItem[];
  totalItems?: number;
  incidentTypes?: string[];
}

const MAX_EVIDENCE_FILTERS = 10;
const MAX_EVIDENCE_FILTER_LENGTH = 100;

function optional(params: URLSearchParams, key: string): string | null {
  const value = params.get(key)?.trim();
  return value && value !== 'all' ? value : null;
}

function evidenceFilters(params: URLSearchParams, key: string): string[] | null {
  const values = [...new Set(params.getAll(key).map((value) => value.trim()).filter(Boolean))];
  if (values.length > MAX_EVIDENCE_FILTERS || values.some((value) => value.length > MAX_EVIDENCE_FILTER_LENGTH)) {
    throw new RangeError(`Invalid ${key} filter`);
  }
  return values.length ? values : null;
}

export async function GET(request: Request) {
  try {
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');

    const params = new URL(request.url).searchParams;
    const requestedPage = Number.parseInt(params.get('page') || '1', 10);
    const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
    const pageSize = params.get('all') === 'true' ? 1000 : PAGE_SIZE;
    const sort = params.get('sort') || 'newest';
    const severity = params.get('severity') || 'all';
    const dayRaw = params.get('day');
    const dayOfWeek = dayRaw === null ? null : Number(dayRaw);
    if (!SORTS.has(sort)) return NextResponse.json({ error: 'Invalid report sort' }, { status: 400 });
    if (!SEVERITIES.has(severity)) return NextResponse.json({ error: 'Invalid report severity' }, { status: 400 });
    if (dayOfWeek !== null && (!Number.isInteger(dayOfWeek) || dayOfWeek < 0 || dayOfWeek > 6)) return NextResponse.json({ error: 'Invalid report weekday' }, { status: 400 });

    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const result = await db.rpc('list_incident_report_summaries', {
      p_page: page,
      p_page_size: pageSize,
      p_search: optional(params, 'search'),
      p_type: optional(params, 'type'),
      p_severity: optional(params, 'severity'),
      p_status: optional(params, 'status'),
      p_generated_after: optional(params, 'after'),
      p_generated_before: optional(params, 'before'),
      p_time_from: optional(params, 'fromTime'),
      p_time_to: optional(params, 'toTime'),
      p_entities: evidenceFilters(params, 'entity'),
      p_instruments: evidenceFilters(params, 'instrument'),
      p_assets: evidenceFilters(params, 'asset'),
      p_day_of_week: dayOfWeek,
      p_sort: sort,
    }) as RpcResult;
    const summaries = Array.isArray(result?.reports) ? result.reports : [];
    const reports = params.get('all') === 'true' ? summaries : await Promise.all(summaries.map(async (report) => {
      if (!isValidR2Key(report.r2Key)) return report;
      try {
        return { ...report, thumbnailUrl: await createR2PlaybackUrl(config, thumbnailKeyForVideo(report.r2Key)) };
      } catch {
        return report;
      }
    }));
    const totalItems = typeof result?.totalItems === 'number' ? result.totalItems : 0;

    return NextResponse.json({
      reports,
      incidentTypes: Array.isArray(result?.incidentTypes) ? result.incidentTypes : [],
      pagination: {
        page,
        pageSize,
        totalItems,
        totalPages: Math.ceil(totalItems / pageSize),
      },
    });
  } catch (error) {
    if (error instanceof RangeError) return NextResponse.json({ error: error.message }, { status: 400 });
    return errorResponse(error, 'Could not load reports');
  }
}
