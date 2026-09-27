// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';

export const dynamic = 'force-dynamic';

const PAGE_SIZE = 20;
const FILTERS = new Set(['all', 'without-report', 'awaiting-selection']);

export interface VideoListItem {
  videoId: string;
  filename: string;
  uploadedAt: string | null;
  source: string | null;
  /** Analyses with an incident (successful or earlier); failed attempts are counted in the video's history. */
  analysesWithReport: number;
  officialRunId: string | null;
}

/**
 * Videos (the parent of every analysis). `filter=without-report` lists videos
 * that have no successful analysis at all, e.g. uploads whose analyses all
 * failed, so they stay discoverable and can be analysed again.
 */
export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const filter = params.get('filter') || 'all';
    if (!FILTERS.has(filter)) return NextResponse.json({ error: 'Invalid video filter' }, { status: 400 });
    const page = Math.max(1, Number.parseInt(params.get('page') || '1', 10) || 1);
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    // videos and incidents are linked by two foreign keys (incident -> its video,
    // and video -> its official run), so every embed names the incident -> video one.
    const base = 'id,filepath,uploaded_datetime,source,selected_model_run_id';
    const query: Record<string, string> = {
      select: filter === 'without-report' ? `${base},incidents!incidents_incident_id_fkey(model_run_id)`
        // Awaiting selection: at least one analysis with a report, and no official report chosen.
        : filter === 'awaiting-selection' ? `${base},incidents!incidents_incident_id_fkey!inner(model_run_id,reports!inner(id))`
          : `${base},incidents!incidents_incident_id_fkey(model_run_id,reports(id))`,
      order: 'uploaded_datetime.desc.nullslast,id.asc',
    };
    if (filter === 'without-report') query.incidents = 'is.null';
    if (filter === 'awaiting-selection') query.selected_model_run_id = 'is.null';
    const { rows, total } = await db.selectPage('videos', query, PAGE_SIZE, (page - 1) * PAGE_SIZE);
    const videos: VideoListItem[] = rows.map((row) => {
      const incidents = Array.isArray(row.incidents) ? (row.incidents as Array<Record<string, unknown>>) : [];
      const filepath = typeof row.filepath === 'string' ? row.filepath : '';
      return {
        videoId: String(row.id),
        filename: filepath.split('/').pop() || String(row.id),
        uploadedAt: typeof row.uploaded_datetime === 'string' ? row.uploaded_datetime : null,
        source: typeof row.source === 'string' ? row.source : null,
        analysesWithReport: incidents.filter((incident) => Array.isArray(incident.reports) && incident.reports.length > 0).length,
        officialRunId: typeof row.selected_model_run_id === 'string' ? row.selected_model_run_id : null,
      };
    });
    return NextResponse.json({ videos, pagination: { page, pageSize: PAGE_SIZE, totalItems: total, totalPages: Math.ceil(total / PAGE_SIZE) }, filter });
  } catch (error) {
    return errorResponse(error, 'Could not load videos');
  }
}
