// SPDX-License-Identifier: Apache-2.0

import { readStoredJson } from '@/lib/r2/stored-json';
import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { repairMissingCrops } from '@/modules/reports/application/repair-missing-crops';
import { repairMissingEmbeddings } from '@/modules/reports/application/repair-missing-embeddings';
import { fetchEvidenceEmbeddings, fetchSummaryEmbedding } from '@/modules/reports/infrastructure/agent/evidence-embeddings';

export const maxDuration = 300;

// Both fields are optional; the body may be empty. Nothing is stored unless dryRun is false.
const requestSchema = z.object({ videoId: z.string().min(1).max(64).optional(), dryRun: z.boolean().optional() }).strict();

/**
 * Repair step: stores evidence_crops for each searchable revision that has image-bearing evidence and no crop rows, and
 * the summary vector of each searchable revision that has none (all videos, or only videoId). A dry run, the default, only
 * lists them. The same repair runs by itself in the job loop (lib/jobs/repair.ts); this route does it on demand and returns
 * {dryRun, revisions (crops), embeddings (summary vectors)}. See repairMissingCrops and repairMissingEmbeddings.
 */
export async function POST(request: Request) {
  try {
    const text = (await request.text()).trim();
    let body: unknown = {};
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    const parsed = requestSchema.safeParse(body);
    if (!parsed.success) {
      return NextResponse.json({ error: 'The body must be empty or contain videoId (string) and dryRun (boolean) only' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    const db = getDbAdapters(config);
    const report = await repairMissingCrops(db, (id) => fetchEvidenceEmbeddings(config, id), parsed.data, readStoredJson(config));
    const embeddings = await repairMissingEmbeddings(db, (summary) => fetchSummaryEmbedding(config, summary), parsed.data);
    return NextResponse.json({ ...report, embeddings: embeddings.revisions });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not repair the evidence crops');
  }
}
