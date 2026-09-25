// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isSupabaseConfigured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { PostgrestClient } from '@/lib/postgrest/client';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { reportFromNotes, type ReportLibraryItem, type ReviewStatus } from '@/lib/reports/storage';

export const dynamic = 'force-dynamic';

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

export async function GET() {
  try {
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config)) throw new Error('Supabase PostgREST is not configured');
    const db = new PostgrestClient(config.supabaseUrl!, config.supabaseServiceRoleKey!);
    const [reports, runs, videos, incidents, reviews, entities, instruments, assets] = await Promise.all([
      db.selectMany('reports', { order: 'generated_datetime.desc' }),
      db.selectMany('model_runs'),
      db.selectMany('videos'),
      db.selectMany('incidents'),
      db.selectMany('review_status'),
      db.selectMany('entities'),
      db.selectMany('instruments'),
      db.selectMany('assets'),
    ]);
    const runById = new Map(runs.map((row) => [String(row.id), row]));
    const videoById = new Map(videos.map((row) => [String(row.id), row]));
    const reviewByKey = new Map(reviews.map((row) => [`${row.incident_id}:${row.model_run_id}`, row]));
    const incidentByKey = new Map(incidents.map((row) => [`${row.incident_id}:${row.model_run_id}`, row]));
    const evidenceByKey = new Map<string, string[]>();
    for (const row of [...entities, ...instruments, ...assets]) {
      const key = `${row.incident_id}:${row.model_run_id}`;
      const values = evidenceByKey.get(key) || [];
      for (const field of ['type', 'name', 'description']) if (text(row[field])) values.push(text(row[field])!);
      evidenceByKey.set(key, values);
    }

    const items = (await Promise.all(reports.map(async (metadata): Promise<ReportLibraryItem | null> => {
      const videoId = String(metadata.incident_id || '');
      const modelRunId = String(metadata.model_run_id || '');
      const run = runById.get(modelRunId);
      const video = videoById.get(videoId);
      const stored = reportFromNotes(run?.notes);
      const incident = incidentByKey.get(`${videoId}:${modelRunId}`);
      if (!run || !video || (!stored && !incident)) return null;
      const review = reviewByKey.get(`${videoId}:${modelRunId}`);
      const r2Key = text(video.filepath);
      let playbackUrl: string | undefined;
      if (r2Key) {
        try { playbackUrl = await createR2PlaybackUrl(config, r2Key); } catch { /* card remains usable */ }
      }
      const incType = text(incident?.type) || stored?.incident_type || 'Unclassified';
      const desc = text(incident?.description) || stored?.description || 'No summary was recorded.';
      const sev = typeof incident?.severity_level === 'number' ? incident.severity_level : stored?.severity || 1;
      const conf = typeof incident?.confidence_score === 'number' ? incident.confidence_score : stored?.confidence ?? 0;

      return {
        reportId: String(metadata.id || stored?.reportId || `${videoId}-${modelRunId}`),
        videoId,
        modelRunId,
        title: stored?.title || `${text(incident?.type) || 'Incident'} report`,
        filename: stored?.filename || r2Key?.split('/').pop() || videoId,
        incident_type: incType,
        description: desc,
        severity: sev,
        confidence: conf,
        generatedAt: text(metadata.generated_datetime) || text(run.run_datetime) || text(video.uploaded_datetime) || '',
        uploadedAt: text(video.uploaded_datetime),
        model: text(run.model_name) || stored?.model || 'Unknown model',
        status: (text(review?.status) || 'unreviewed') as ReviewStatus,
        verifiedBy: text(review?.verified_by),
        verifiedAt: text(review?.verified_at),
        editedBy: text(review?.edited_by),
        editedAt: text(review?.edited_at),
        playbackUrl,
        r2Key,
        sensorId: text(video.source),
        searchableEvidence: (evidenceByKey.get(`${videoId}:${modelRunId}`) || []).join(' '),
      };
    }))).filter((item): item is ReportLibraryItem => item !== null);
    return NextResponse.json({ reports: items });
  } catch (error) {
    return errorResponse(error, 'Could not load reports');
  }
}
