// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getAnalysisStore, getDbAdapters, getEvidenceLinker, getIncidentSynthesizer, getIncidentVideos } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { BuildReportError, buildIncidentReport } from '@/modules/reports/application/build-incident-report';

export const maxDuration = 180;

const requestSchema = z.object({ note: z.string().max(500).nullish() }).strict();

// Regenerate: a new AI version of the incident from the latest stored analysis of each of its
// current videos. Nothing is re-analysed. The body is optional: { note? }.
export async function POST(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const { incidentId } = await context.params;
    const id = Number(incidentId);
    const text = await request.text();
    const parsed = requestSchema.safeParse(text.trim() ? JSON.parse(text.trim()) : {});
    if (!Number.isSafeInteger(id) || id <= 0 || !parsed.success) {
      return NextResponse.json({ error: 'The incident id must be a positive integer and the body may only hold a note' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    const built = await buildIncidentReport(
      {
        incidents: getDbAdapters(config).incidentReports,
        videos: getIncidentVideos(config),
        ...getAnalysisStore(config),
        synthesizer: getIncidentSynthesizer(config),
        linker: getEvidenceLinker(config),
      },
      { incidentId: id, note: parsed.data.note },
    );
    return NextResponse.json({ built });
  } catch (error) {
    if (error instanceof SyntaxError) return NextResponse.json({ error: 'The body must be valid JSON' }, { status: 400 });
    if (error instanceof BuildReportError) {
      return NextResponse.json({ error: error.message, ...error.details }, { status: error.status });
    }
    return rejectionResponse(error) ?? errorResponse(error, 'Could not build the report');
  }
}
