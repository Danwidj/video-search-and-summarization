// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getAnalysisStore, getDbAdapters, getMatchingPorts } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { evaluateIncident, MatchJudgeError } from '@/modules/matching/application/evaluate-incident';

// Compares one incident with every other and records the likely matches as pending suggestions.
// Called when an incident gains a video or a report, so a batch finds itself in any finishing order.
export const maxDuration = 300;

const bodySchema = z.object({ incidentId: z.number().int().positive() }).strict();

export async function POST(request: Request) {
  try {
    const parsed = bodySchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'incidentId is required' }, { status: 400 });
    const config = getServiceConfiguration();
    const result = await evaluateIncident(
      { reports: getDbAdapters(config).incidentReports, analyses: getAnalysisStore(config).analyses, matching: getMatchingPorts(config) },
      parsed.data.incidentId,
      AbortSignal.timeout(240_000),
    );
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof MatchJudgeError) return NextResponse.json({ error: error.message }, { status: error.status });
    return rejectionResponse(error) ?? errorResponse(error, 'Could not evaluate the incident for matches');
  }
}
